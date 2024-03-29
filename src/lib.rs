use breezyshim::branch::Branch;
use breezyshim::dirty_tracker::DirtyTracker;
use breezyshim::tree::{Error as TreeError, MutableTree, Tree, TreeChange, WorkingTree};
use breezyshim::workspace::reset_tree;
use debian_changelog::ChangeLog;
#[cfg(feature = "python")]
use pyo3::PyErr;
use std::str::FromStr;

pub mod changelog;
pub mod config;
pub mod debmutateshim;
pub mod detect_gbp_dch;
pub mod patches;
pub mod publish;
pub mod release_info;
pub mod salsa;
pub mod svp;
pub mod vcs;

// TODO(jelmer): Import this from ognibuild
pub const DEFAULT_BUILDER: &str = "sbuild --no-clean-source";

#[derive(Debug)]
pub enum ApplyError<R, E> {
    /// Error from the callback
    CallbackError(E),
    /// Error from the tree
    TreeError(TreeError),
    /// No changes made
    NoChanges(R),
}

impl<R, E> From<TreeError> for ApplyError<R, E> {
    fn from(e: TreeError) -> Self {
        ApplyError::TreeError(e)
    }
}

/// Apply a change in a clean tree.
///
/// This will either run a callback in a tree, or if the callback fails,
/// revert the tree to the original state.
///
/// The original tree should be clean; you can run check_clean_tree() to
/// verify this.
///
/// # Arguments
/// * `local_tree` - Local tree
/// * `subpath` - Subpath to apply changes to
/// * `basis_tree` - Basis tree to reset to
/// * `dirty_tracker` - Dirty tracker
/// * `applier` - Callback to apply changes
///
/// # Returns
/// * `Result<(R, Vec<TreeChange>, Option<Vec<std::path::PathBuf>>), E>` - Result of the callback,
///   the changes made, and the files that were changed
pub fn apply_or_revert<R, E>(
    local_tree: &WorkingTree,
    subpath: &std::path::Path,
    basis_tree: &dyn Tree,
    dirty_tracker: Option<&DirtyTracker>,
    applier: impl FnOnce(&std::path::Path) -> Result<R, E>,
) -> Result<(R, Vec<TreeChange>, Option<Vec<std::path::PathBuf>>), ApplyError<R, E>> {
    let r = match applier(local_tree.abspath(subpath).unwrap().as_path()) {
        Ok(r) => r,
        Err(e) => {
            reset_tree(local_tree, Some(basis_tree), Some(subpath), dirty_tracker).unwrap();
            return Err(ApplyError::CallbackError(e));
        }
    };

    let specific_files = if let Some(dirty_tracker) = dirty_tracker {
        let mut relpaths: Vec<_> = dirty_tracker.relpaths().into_iter().collect();
        relpaths.sort();
        // Sort paths so that directories get added before the files they
        // contain (on VCSes where it matters)
        local_tree.add(
            relpaths
                .iter()
                .filter_map(|p| {
                    if local_tree.has_filename(p) && local_tree.is_ignored(p).is_some() {
                        Some(p.as_path())
                    } else {
                        None
                    }
                })
                .collect::<Vec<_>>()
                .as_slice(),
        )?;
        let specific_files = relpaths
            .into_iter()
            .filter(|p| local_tree.is_versioned(p))
            .collect::<Vec<_>>();
        if specific_files.is_empty() {
            return Err(ApplyError::NoChanges(r));
        }
        Some(specific_files)
    } else {
        local_tree.smart_add(&[local_tree.abspath(subpath).unwrap().as_path()])?;
        if subpath.as_os_str().is_empty() {
            None
        } else {
            Some(vec![subpath.to_path_buf()])
        }
    };

    if local_tree.supports_setting_file_ids() {
        breezyshim::rename_map::guess_renames(basis_tree, local_tree).unwrap();
    }

    let specific_files_ref = specific_files
        .as_ref()
        .map(|fs| fs.iter().map(|p| p.as_path()).collect::<Vec<_>>());

    let changes = local_tree
        .iter_changes(
            basis_tree,
            specific_files_ref.as_deref(),
            Some(false),
            Some(true),
        )?
        .collect::<Result<Vec<_>, _>>()?;

    if local_tree.get_parent_ids()?.len() <= 1 && changes.is_empty() {
        return Err(ApplyError::NoChanges(r));
    }

    Ok((r, changes, specific_files))
}

pub enum ChangelogError {
    NotDebianPackage(std::path::PathBuf),
    Python(PyErr),
}

impl std::fmt::Display for ChangelogError {
    fn fmt(&self, f: &mut std::fmt::Formatter) -> std::fmt::Result {
        match self {
            ChangelogError::NotDebianPackage(path) => {
                write!(f, "Not a Debian package: {}", path.display())
            }
            ChangelogError::Python(e) => write!(f, "{}", e),
        }
    }
}

#[cfg(feature = "python")]
impl From<PyErr> for ChangelogError {
    fn from(e: PyErr) -> Self {
        use pyo3::import_exception;

        import_exception!(breezy.transport, NoSuchFile);

        pyo3::Python::with_gil(|py| {
            if e.is_instance_of::<NoSuchFile>(py) {
                return ChangelogError::NotDebianPackage(
                    e.value(py).getattr("path").unwrap().extract().unwrap(),
                );
            } else {
                ChangelogError::Python(e)
            }
        })
    }
}

pub fn add_changelog_entry(
    working_tree: &WorkingTree,
    changelog_path: &std::path::Path,
    entry: &[&str],
) -> Result<(), ChangelogError> {
    let f = match working_tree.get_file(changelog_path) {
        Ok(f) => f,
        Err(breezyshim::tree::Error::NoSuchFile(_)) => {
            return Err(ChangelogError::NotDebianPackage(
                working_tree.abspath(changelog_path).unwrap(),
            ))
        }
        Err(e) => panic!("Unexpected error: {}", e),
    };
    let mut cl = ChangeLog::read(f).unwrap();

    cl.auto_add_change(
        entry,
        debian_changelog::get_maintainer().unwrap(),
        None,
        None,
    );

    working_tree
        .put_file_bytes_non_atomic(changelog_path, cl.to_string().as_bytes())
        .unwrap();

    Ok(())
}

#[derive(
    Clone,
    Copy,
    PartialEq,
    Eq,
    Debug,
    Default,
    PartialOrd,
    Ord,
    serde::Serialize,
    serde::Deserialize,
)]
pub enum Certainty {
    #[serde(rename = "possible")]
    Possible,
    #[serde(rename = "likely")]
    Likely,
    #[serde(rename = "confident")]
    Confident,
    #[default]
    #[serde(rename = "certain")]
    Certain,
}

impl FromStr for Certainty {
    type Err = String;

    fn from_str(value: &str) -> Result<Self, Self::Err> {
        match value {
            "certain" => Ok(Certainty::Certain),
            "confident" => Ok(Certainty::Confident),
            "likely" => Ok(Certainty::Likely),
            "possible" => Ok(Certainty::Possible),
            _ => Err(format!("Invalid certainty: {}", value)),
        }
    }
}

impl std::fmt::Display for Certainty {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Certainty::Certain => write!(f, "certain"),
            Certainty::Confident => write!(f, "confident"),
            Certainty::Likely => write!(f, "likely"),
            Certainty::Possible => write!(f, "possible"),
        }
    }
}

#[cfg(feature = "python")]
impl pyo3::FromPyObject<'_> for Certainty {
    fn extract(ob: &pyo3::PyAny) -> pyo3::PyResult<Self> {
        let s = ob.extract::<String>()?;
        Certainty::from_str(&s).map_err(pyo3::exceptions::PyValueError::new_err)
    }
}

#[cfg(feature = "python")]
impl pyo3::ToPyObject for Certainty {
    fn to_object(&self, py: pyo3::Python) -> pyo3::PyObject {
        self.to_string().to_object(py)
    }
}

/// Check if the actual certainty is sufficient.
///
/// # Arguments
///
/// * `actual_certainty` - Actual certainty with which changes were made
/// * `minimum_certainty` - Minimum certainty to keep changes
///
/// # Returns
///
/// * `bool` - Whether the actual certainty is sufficient
pub fn certainty_sufficient(
    actual_certainty: Certainty,
    minimum_certainty: Option<Certainty>,
) -> bool {
    if let Some(minimum_certainty) = minimum_certainty {
        actual_certainty >= minimum_certainty
    } else {
        true
    }
}

/// Return the minimum certainty from a list of certainties.
pub fn min_certainty(certainties: &[Certainty]) -> Option<Certainty> {
    certainties.iter().min().cloned()
}

/// Get the committer string for a tree
pub fn get_committer(working_tree: &WorkingTree) -> String {
    pyo3::Python::with_gil(|py| {
        let m = py.import("lintian_brush")?;
        let get_committer = m.getattr("get_committer")?;
        get_committer.call1((&working_tree.0,))?.extract()
    })
    .unwrap()
}

/// Check whether there are any control files present in a tree.
///
/// # Arguments
///
///   * `tree`: tree to check
///   * `subpath`: subpath to check
///
/// # Returns
///
/// whether control file is present
pub fn control_file_present(tree: &dyn Tree, subpath: &std::path::Path) -> bool {
    for name in [
        "debian/control",
        "debian/control.in",
        "control",
        "control.in",
        "debian/debcargo.toml",
    ] {
        let name = subpath.join(name);
        if tree.has_filename(name.as_path()) {
            return true;
        }
    }
    false
}

pub fn is_debcargo_package(tree: &dyn Tree, subpath: &std::path::Path) -> bool {
    tree.has_filename(subpath.join("debian/debcargo.toml").as_path())
}

pub fn control_files_in_root(tree: &dyn Tree, subpath: &std::path::Path) -> bool {
    let debian_path = subpath.join("debian");
    if tree.has_filename(debian_path.as_path()) {
        return false;
    }

    let control_path = subpath.join("control");
    if tree.has_filename(control_path.as_path()) {
        return true;
    }

    tree.has_filename(subpath.join("control.in").as_path())
}

pub fn branch_vcs_type(branch: &dyn Branch) -> String {
    pyo3::Python::with_gil(|py| {
        let repo = branch.to_object(py).getattr(py, "repository").unwrap();
        if repo.as_ref(py).hasattr("_git").unwrap() {
            Ok::<String, PyErr>("git".to_string())
        } else {
            Ok::<String, PyErr>("bzr".to_string())
        }
    })
    .unwrap()
}

pub fn parseaddr(input: &str) -> Option<(Option<String>, Option<String>)> {
    if let Some((_whole, name, addr)) =
        lazy_regex::regex_captures!(r"(?:(?P<name>[^<]*)\s*<)?(?P<addr>[^<>]*)>?", input)
    {
        let name = Some(name.trim().to_string());
        let addr = Some(addr.trim().to_string());

        return Some((name, addr));
    } else if let Some((_whole, addr)) = lazy_regex::regex_captures!(r"(?P<addr>[^<>]*)", input) {
        let addr = Some(addr.trim().to_string());

        return Some((None, addr));
    } else if input.is_empty() {
        return None;
    } else if !input.contains('<') {
        return Some((None, Some(input.to_string())));
    }
    None
}

pub fn gbp_dch(path: &std::path::Path) -> Result<(), std::io::Error> {
    let mut cmd = std::process::Command::new("gbp");
    cmd.arg("dch").arg("--ignore-branch");
    cmd.current_dir(path);
    let status = cmd.status()?;
    if !status.success() {
        return Err(std::io::Error::new(
            std::io::ErrorKind::Other,
            format!("gbp dch failed: {}", status),
        ));
    }
    Ok(())
}
