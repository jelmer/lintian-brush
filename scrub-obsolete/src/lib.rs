use std::path::PathBuf;
use debian_analyzer::editor::{Editor, EditorError, MutableTreeEdit};
use deb822_lossless::lossless::Paragraph;
use debversion::Version;
use std::collections::HashMap;
use debian_control::lossless::relations::{Entry, Relations};
use debian_control::relations::VersionConstraint;
use debian_control::{Source, Binary};
use breezyshim::error::Error as BrzError;
use breezyshim::commit::NullCommitReporter;
use breezyshim::workingtree::WorkingTree;
use crate::action::Action;
use std::path::Path;

pub mod action;
pub mod dummy_transitional;
pub mod package_checker;
use package_checker::PackageChecker;

pub const DEFAULT_VALUE_MULTIARCH_HINT: usize = 30;

pub fn note_changelog_policy(policy: bool, msg: &str) {
    lazy_static::lazy_static! {
        static ref CHANGELOG_POLICY_NOTED: std::sync::Mutex<bool> = std::sync::Mutex::new(false);
    }
    if let Ok(mut policy_noted) = CHANGELOG_POLICY_NOTED.lock() {
        if !*policy_noted {
            let extra = if policy {
                "Specify --no-update-changelog to override."
            } else {
                "Specify --update-changelog to override."
            };
            log::info!("{} {}", msg, extra);
        }
        *policy_noted = true;
    }
}

fn depends_obsolete(
    latest_version: &Version, kind: VersionConstraint, req_version: &Version
) -> bool {
    match kind {
        VersionConstraint::GreaterThanEqual => latest_version >= req_version,
        VersionConstraint::GreaterThan => latest_version > req_version,
        VersionConstraint::Equal => false,
        _ => false,
    }
}

fn conflict_obsolete(
    latest_version: &Version, kind: VersionConstraint, req_version: &Version
) -> bool {
    match kind {
        VersionConstraint::LessThan => latest_version >= req_version,
        VersionConstraint::LessThanEqual | VersionConstraint::Equal => latest_version > req_version,
        _ => false,
    }
}

async fn drop_obsolete_depends(
    entry: &mut Entry,
    checker: &PackageChecker,
    keep_minimum_versions: bool
) -> Result<Vec<Action>, ScrubObsoleteError> {
    let mut actions = vec![];
    let mut to_remove = vec![];
    let mut to_replace = vec![];
    for (i, mut pkgrel) in entry.relations().enumerate() {
        if let Some(replacement) = checker.replacement(&pkgrel.name()).await.unwrap() {
            let parsed_replacement: Relations = replacement.parse().unwrap();
            if parsed_replacement.entries().count() > 1 {
                log::warn!(
                    "Unable to replace multi-package {:?}", replacement
                );
            } else {
                // If the replacement is already included in the entry, we can drop the old
                // package.
                let newrel: Entry = replacement.parse().unwrap();
                if debian_analyzer::relations::is_relation_implied(&newrel, &entry) {
                    to_remove.push(i);
                    actions.push(Action::DropTransition(pkgrel));
                } else {
                    // Otherwise, we can replace the old package with the new one.
                    to_replace.push((i, newrel.relations().next().unwrap()));
                    actions.push(Action::ReplaceTransition(pkgrel, vec![replacement.parse().unwrap()]))
                }
            }
        } else if pkgrel.version().is_some() && pkgrel.name() != "debhelper" {
            let compat_version = checker.package_version(&pkgrel.name()).await?;
            log::debug!(
                "Relation: {}. Upgrade release {} has {:?} ",
                pkgrel,
                checker.release(),
                compat_version,
            );
            if compat_version.as_ref().map(|cv| depends_obsolete(cv, pkgrel.version().unwrap().0, &pkgrel.version().unwrap().1)).unwrap_or(false) {
                // If the package is essential, we don't need to maintain a dependency on it.
                if checker.is_essential(&pkgrel.name()).await?.unwrap_or(false) {
                    actions.push(Action::DropEssential(pkgrel));
                    return Ok(actions);
                }
                if !keep_minimum_versions {
                    pkgrel.set_version(None);
                    actions.push(Action::DropMinimumVersion(pkgrel))
                }
            }
        }
    }

    for (i, newrel) in to_replace {
        entry.replace(i, newrel);
    }

    for i in to_remove.into_iter().rev() {
        entry.get_relation(i).unwrap().remove();
    }

    Ok(actions)
}

async fn drop_obsolete_conflicts(checker: &PackageChecker, entry: &mut Entry) -> Result<Vec<Action>, ScrubObsoleteError> {
    let mut to_remove = vec![];
    let mut actions = vec![];
    for (i, pkgrel) in entry.relations().enumerate() {
        if let Some((vc, version)) = pkgrel.version() {
            let compat_version = checker.package_version(&pkgrel.name()).await?;
            if compat_version.map(|cv| conflict_obsolete(
                &cv, vc, &version
            )).unwrap_or(false) {
                actions.push(Action::DropObsoleteConflict(pkgrel));
                to_remove.push(i);
                continue;
            }
        }
    }
    for i in to_remove.into_iter().rev() {
        entry.get_relation(i).unwrap().remove();
    }
    Ok(actions)
}

fn update_depends(
    base: &mut Paragraph,
    field: &str,
    checker: &PackageChecker,
    keep_minimum_versions: bool
) -> Vec<Action> {
    filter_relations(
        base,
        field,
        |oldrelation: &mut Entry| {
            let rt = tokio::runtime::Runtime::new().unwrap();
            rt.block_on(drop_obsolete_depends(
                oldrelation, checker, keep_minimum_versions
            )).unwrap()
        }
    )
}

/// Update a relations field.
fn filter_relations(
    base: &mut Paragraph, field: &str, cb: impl Fn(&mut Entry) -> Vec<Action>
) -> Vec<Action> {
    let old_contents = base.get(field).unwrap_or_else(|| "".to_string());

    let mut relations: Relations = old_contents.parse().unwrap();

    let mut to_remove = vec![];
    let mut all_actions = vec![];
    for (i, mut entry) in relations.entries().enumerate() {
        let actions = cb(&mut entry);
        all_actions.extend(actions);
        if !entry.is_empty() {
            to_remove.push(i);
        }
    }

    for i in to_remove.into_iter().rev() {
        relations.remove(i);
    }

    if !all_actions.is_empty() {
        if relations.is_empty() {
            base.remove(field);
        } else {
            base.insert(field, &relations.to_string());
        }
        return all_actions;
    }
    return vec![];
}

fn update_conflicts(
    base: &mut Paragraph, field: &str, checker: &PackageChecker
) -> Vec<Action> {
    filter_relations(
        base,
        field,
        |oldrelation: &mut Entry| -> Vec<Action> {
            let rt = tokio::runtime::Runtime::new().unwrap();
            rt.block_on(drop_obsolete_conflicts(checker, oldrelation)).unwrap()
        }
    )
}


fn drop_old_source_relations(
    source: &mut Source,
    build_checker: &PackageChecker,
    compat_release: &str, keep_minimum_depends_versions: bool
) -> Vec<(String, Vec<Action>, String)> {
    let mut ret = vec![];
    for field in [
        "Build-Depends",
        "Build-Depends-Indep",
        "Build-Depends-Arch",
    ] {
        let actions = update_depends(
            source.as_mut_deb822(),
            field,
            &build_checker,
            keep_minimum_depends_versions,
        );
        if !actions.is_empty() {
            ret.push((field.to_string(), actions, compat_release.to_string()))
        }
    }
    for field in [
        "Build-Conflicts",
        "Build-Conflicts-Indep",
        "Build-Conflicts-Arch",
    ] {
        let actions = update_conflicts(source.as_mut_deb822(), field, &build_checker);
        if !actions.is_empty() {
            ret.push((field.to_string(), actions, compat_release.to_string()));
        }
    }
    ret
}

fn drop_old_binary_relations(
    runtime_checker: &PackageChecker,
    binary: &mut Binary,
    upgrade_release: &str,
    keep_minimum_depends_versions: bool
) -> Vec<(String, Vec<Action>, String)> {
    let mut ret = vec![];
    for field in ["Depends", "Suggests", "Recommends", "Pre-Depends"] {
        let actions = update_depends(
            binary.as_mut_deb822(),
            field,
            runtime_checker,
            keep_minimum_depends_versions,
        );
        if !actions.is_empty() {
            ret.push((field.to_string(), actions, upgrade_release.to_string()));
        }
    }

    for field in ["Conflicts", "Replaces", "Breaks"] {
        let actions = update_conflicts(binary.as_mut_deb822(), field, runtime_checker);
        if !actions.is_empty() {
            ret.push((field.to_string(), actions, upgrade_release.to_string()));
        }
    }

    ret
}


fn drop_old_relations(
    editor: &impl Editor<debian_control::Control>,
    build_checker: &PackageChecker,
    runtime_checker: &PackageChecker,
    compat_release: &str,
    upgrade_release: &str,
    keep_minimum_depends_versions: bool
) -> Vec<(Option<String>, Vec<(String, Vec<Action>, String)>)> {
    let mut actions = vec![];
    let mut source_actions = vec![];

    if let Some(mut source) = editor.source() {
        source_actions.extend(
            drop_old_source_relations(
                &mut source,
                build_checker,
                compat_release,
                keep_minimum_depends_versions,
            )
        );
    }

    if !source_actions.is_empty() {
        actions.push((None, source_actions));
    }

    for mut binary in editor.binaries() {
        let binary_actions = drop_old_binary_relations(
            runtime_checker,
            &mut binary,
            upgrade_release,
            keep_minimum_depends_versions,
        );
        if !binary_actions.is_empty() {
            actions.push((binary.name(), binary_actions));
        }
    }

    actions
}


fn update_maintscripts(
    wt: &WorkingTree,
    debian_path: &Path,
    checker: PackageChecker,
    allow_reformatting: bool,
) -> Result<Vec<(PathBuf, Vec<(String, Version)>)>, ScrubObsoleteError> {
    let mut ret = vec![];
    for entry in std::fs::read_dir(wt.abspath(debian_path).unwrap()).unwrap() {
        let entry = entry.unwrap();
        if !(
            entry.file_name() == "maintscript" || entry.file_name().to_str().unwrap().ends_with(".maintscript")
        ) {
            continue;
        }
        let mut editor = wt.edit_file::<debian_analyzer::maintscripts::Maintscript>(&entry.path(), false, allow_reformatting)?;
        let mut can_drop = |p: &str, v: &Version| -> bool{
            let rt = tokio::runtime::Runtime::new().unwrap();
            let compat_version = rt.block_on(checker.package_version(p)).unwrap();
            compat_version.map(|cv| &cv > v).unwrap_or(false)
        };

        let removed = drop_obsolete_maintscript_entries(&mut editor, &mut can_drop);
        if !removed.is_empty() {
            ret.push((debian_path.join(entry.file_name()), removed));
        }

        editor.commit()?;
    }
    Ok(ret)
}

pub struct ScrubObsoleteResult {
    specific_files: Vec<PathBuf>,
    control_actions: Vec<(Option<String>, Vec<(String, Vec<Action>, String)>)>,
    maintscript_removed: Vec<(PathBuf, Vec<(String, Version)>, String)>
}

impl ScrubObsoleteResult {
    pub fn any_changes(&self) -> bool {
        return !self.control_actions.is_empty() || !self.maintscript_removed.is_empty();
    }

    pub fn value(&self) -> usize {
        let mut value = DEFAULT_VALUE_MULTIARCH_HINT;
        for (_para, changes) in &self.control_actions {
            for (_field, actions, _) in changes {
                value += actions.len() * 2;
            }
        }
        for (_, removed, _) in &self.maintscript_removed {
            value += removed.len();
        }
        value
    }

    fn itemized(&self) -> HashMap<String, Vec<String>> {
        let mut summary = HashMap::new();
        for (para, changes) in &self.control_actions {
            for (field, actions, release) in changes {
                for action in actions {
                    if let Some(para) = para {
                        summary
                            .entry(release.to_string())
                            .or_insert_with(Vec::new)
                            .push(format!("{}: {} in {}.", para, action, field));
                    } else {
                        summary
                            .entry(release.to_string())
                            .or_insert_with(Vec::new)
                            .push(format!("{}: {}.", field, action));
                    }
                }
            }
        }
        if !self.maintscript_removed.is_empty() {
            let total_entries: usize = self.maintscript_removed.iter().map(|(_, entries, _)| entries.len()).sum();
            summary
                .entry(self.maintscript_removed[0].2.clone())
                .or_insert_with(Vec::new)
                .push(format!(
                    "Remove {} maintscript entries from {} files.",
                    total_entries,
                    self.maintscript_removed.len()
                ));
        }
        summary
    }
}

async fn _scrub_obsolete(
    wt: &WorkingTree,
    debian_path: &Path,
    compat_release: &str,
    upgrade_release: &str,
    allow_reformatting: bool,
    keep_minimum_depends_versions: bool,
) -> Result<ScrubObsoleteResult, ScrubObsoleteError> {
    let mut specific_files = vec![];
    let source_package_checker = PackageChecker::new(compat_release, true).await;
    let binary_package_checker = PackageChecker::new(upgrade_release, false).await;
    let control_actions = if !debian_path.join("debcargo.toml").exists() {
        let control_path = debian_path.join("control");
        let control = debian_analyzer::control::TemplatedControlEditor::open(&control_path)?;
        let control_actions = drop_old_relations(&control, &source_package_checker, &binary_package_checker, compat_release, upgrade_release, keep_minimum_depends_versions);
        let changed_files = control.commit()?;
        specific_files.extend(wt.safe_relpath_files(changed_files.iter().map(|s| s.as_path()).collect::<Vec<_>>().as_slice(), true, false)?);
        control_actions
    } else {
        vec![]
    };

    let mut maintscript_removed = vec![];
    for (path, removed) in update_maintscripts(
        wt, debian_path, binary_package_checker, allow_reformatting
    )? {
        if !removed.is_empty() {
            specific_files.push(path.clone());
            maintscript_removed.push((path, removed, upgrade_release.to_string()));
        }
    }

    Ok(ScrubObsoleteResult {
        specific_files,
        control_actions,
        maintscript_removed,
    })
}

#[derive(Debug)]
pub enum ScrubObsoleteError {
    NotDebianPackage(PathBuf),
    EditorError(EditorError),
    BrzError(BrzError),
    SqlxError(sqlx::Error),
}

impl std::fmt::Display for ScrubObsoleteError {
    fn fmt(&self, f: &mut std::fmt::Formatter) -> std::fmt::Result {
        match self {
            ScrubObsoleteError::NotDebianPackage(path) => write!(f, "Not a Debian package: {:?}", path),
            ScrubObsoleteError::EditorError(e) => write!(f, "Editor error: {}", e),
            ScrubObsoleteError::BrzError(e) => write!(f, "Breezy error: {}", e),
            ScrubObsoleteError::SqlxError(e) => write!(f, "SQLx error: {}", e),
        }
    }
}

impl std::error::Error for ScrubObsoleteError {}

impl From<EditorError> for ScrubObsoleteError {
    fn from(e: EditorError) -> Self {
        ScrubObsoleteError::EditorError(e)
    }
}

impl From<BrzError> for ScrubObsoleteError {
    fn from(e: BrzError) -> Self {
        ScrubObsoleteError::BrzError(e)
    }
}

impl From<sqlx::Error> for ScrubObsoleteError {
    fn from(e: sqlx::Error) -> Self {
        ScrubObsoleteError::SqlxError(e)
    }
}

/// Scrub obsolete entries.
pub fn scrub_obsolete(
    wt: WorkingTree,
    subpath: &Path,
    compat_release: &str,
    upgrade_release: &str,
    update_changelog: Option<bool>,
    allow_reformatting: bool,
    keep_minimum_depends_versions: bool,
    transitions: Option<HashMap<String, String>>,
) -> Result<ScrubObsoleteResult, ScrubObsoleteError> {
    let debian_path = if debian_analyzer::control_files_in_root(&wt, subpath) {
        subpath.to_path_buf()
    } else {
        subpath.join("debian")
    };

    let rt = tokio::runtime::Runtime::new().unwrap();

    let result = rt.block_on(_scrub_obsolete(
        &wt,
        &debian_path,
        compat_release,
        upgrade_release,
        allow_reformatting,
        keep_minimum_depends_versions,
    ))?;

    if !result.any_changes() {
        return Ok(result);
    }

    let mut specific_files = result.specific_files.clone();
    let summary = result.itemized();

    let changelog_path = debian_path.join("changelog");

    let update_changelog = if let Some(update_changelog) = update_changelog {
        update_changelog
    } else {
        if let Some(dch_guess) = debian_analyzer::detect_gbp_dch::guess_update_changelog(&wt, &debian_path, None) {
            note_changelog_policy(dch_guess.update_changelog, &dch_guess.explanation);
            dch_guess.update_changelog
        } else {
            // If we can't guess, default to updating the changelog.
            true
        }
    };

    if update_changelog {
        let mut lines = vec![];
        for (release, entries) in summary.iter() {
            let rev_aliases = debian_analyzer::release_info::release_aliases(release, None);
            let mut line = format!("Remove constraints unnecessary since {}", release);
            for alias in rev_aliases {
                line += &format!(" ({})", alias);
            }
            line += ":";
            lines.push(line);
            lines.extend(entries.iter().map(|x| format!("* {}", x)));
        }
        debian_analyzer::add_changelog_entry(&wt, &changelog_path, lines.iter().map(|x| x.as_str()).collect::<Vec<_>>().as_slice())?;
        specific_files.push(changelog_path);
    }

    let mut lines = vec![];
    for (release, _entries) in summary.iter() {
        let rev_aliases = debian_analyzer::release_info::release_aliases(release, None);
        let mut line = format!("Remove constraints unnecessary since {}", release);
        for alias in rev_aliases {
            line += &format!(" ({})", alias);
        }
        line += ":";

        lines.push(line);
    }
    lines.extend(["".to_string(), "Changes-By: deb-scrub-obsolete".to_string()]);

    let committer = debian_analyzer::get_committer(&wt);

    match wt.build_commit()
        .specific_files(specific_files.iter().map(|x| x.as_path()).collect::<Vec<_>>().as_slice())
        .message(&lines.join("\n"))
        .allow_pointless(false)
        .reporter(&NullCommitReporter::new())
        .committer(&committer)
        .commit() {
        Ok(_) | Err(BrzError::PointlessCommit) => {}
        Err(e) => { return Err(e.into()); }
    }

    Ok(result)
}

/// Drop obsolete entries from a maintscript file.
///
/// # Arguments
/// * `editor` - editor to use to access the maintscript
/// * `should_remove` - callable to check whether a package/version tuple is obsolete
///
/// # Returns
/// list of tuples with index, package, version of entries that were removed
fn drop_obsolete_maintscript_entries(
    editor: &mut dyn Editor<debian_analyzer::maintscripts::Maintscript>, should_remove: &mut dyn FnMut(&str, &Version) -> bool,
) -> Vec<(String, Version)> {
    let mut to_remove = vec![];
    let mut ret = vec![];
    for (i, entry) in editor.entries().iter().enumerate() {
        if let (Some(package), Some(version)) = (entry.package(), entry.prior_version()) {
            if should_remove(package, version) {
                to_remove.push(i);
                ret.push((package.clone(), version.clone()));
            }
        }
    }
    for i in to_remove.into_iter().rev() {
        editor.remove(i);
    }
    ret
}