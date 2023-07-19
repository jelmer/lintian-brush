use debversion::Version;
use lazy_regex::regex_replace;
use std::collections::{HashMap, HashSet};
use std::fs::File;
use std::io::{BufReader, Read};
use std::process::Command;
use std::str::FromStr;

use indicatif::ProgressBar;

use crate::debianshim::Changelog;
use breezyshim::dirty_tracker::{get_dirty_tracker, DirtyTracker};
use breezyshim::tree::{CommitError, Tree, TreeChange, WorkingTree};
use breezyshim::workspace::{check_clean_tree, reset_tree};
use breezyshim::RevisionId;

pub mod config;
pub mod debianshim;
pub mod py;
pub mod svp;

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

#[derive(Clone, PartialEq, Eq, Debug, serde::Serialize, serde::Deserialize)]
pub enum PackageType {
    #[serde(rename = "source")]
    Source,
    #[serde(rename = "binary")]
    Binary,
}

impl FromStr for PackageType {
    type Err = String;

    fn from_str(value: &str) -> Result<Self, Self::Err> {
        match value {
            "source" => Ok(PackageType::Source),
            "binary" => Ok(PackageType::Binary),
            _ => Err(format!("Invalid package type: {}", value)),
        }
    }
}

impl ToString for PackageType {
    fn to_string(&self) -> String {
        match self {
            PackageType::Source => "source".to_string(),
            PackageType::Binary => "binary".to_string(),
        }
    }
}

#[derive(Clone, PartialEq, Eq, Debug, serde::Serialize, serde::Deserialize)]
pub struct LintianIssue {
    pub package: Option<String>,
    pub package_type: Option<PackageType>,
    pub tag: Option<String>,
    pub info: Option<Vec<String>>,
}

impl LintianIssue {
    pub fn json(&self) -> serde_json::Value {
        serde_json::json!({
            "package": self.package,
            "package_type": self.package_type.as_ref().map(|t| t.to_string()),
            "tag": self.tag,
            "info": self.info,
        })
    }

    pub fn from_json(value: serde_json::Value) -> serde_json::Result<Self> {
        serde_json::from_value(value)
    }

    pub fn just_tag(tag: String) -> Self {
        Self {
            package: None,
            package_type: None,
            tag: Some(tag),
            info: None,
        }
    }
}

#[derive(Clone, PartialEq, Eq, Debug)]
pub enum LintianIssueParseError {
    InvalidPackageType(String),
}

impl pyo3::FromPyObject<'_> for LintianIssue {
    fn extract(ob: &pyo3::PyAny) -> pyo3::PyResult<Self> {
        let package = ob.getattr("package")?.extract::<Option<String>>()?;
        let package_type = ob
            .getattr("package_type")?
            .extract::<Option<String>>()?
            .map(|s| {
                s.parse::<PackageType>()
                    .map_err(|e| pyo3::exceptions::PyValueError::new_err((e,)))
            })
            .transpose()?;
        let tag = ob.getattr("tag")?.extract::<Option<String>>()?;
        let info = ob.getattr("info")?.extract::<Option<Vec<String>>>()?;
        Ok(Self {
            package,
            package_type,
            tag,
            info,
        })
    }
}

impl std::fmt::Display for LintianIssueParseError {
    fn fmt(&self, f: &mut std::fmt::Formatter) -> std::fmt::Result {
        match self {
            LintianIssueParseError::InvalidPackageType(s) => {
                write!(f, "Invalid package type: {}", s)
            }
        }
    }
}

impl std::error::Error for LintianIssueParseError {}

impl TryFrom<&str> for LintianIssue {
    type Error = LintianIssueParseError;

    fn try_from(value: &str) -> Result<Self, Self::Error> {
        let value = value.trim();
        let package_type;
        let package;
        let after = if let Some((before, after)) = value.split_once(':') {
            if let Some((package_type_str, package_str)) = before.trim().split_once(' ') {
                package_type = Some(match package_type_str {
                    "source" => PackageType::Source,
                    "binary" => PackageType::Binary,
                    _ => {
                        return Err(LintianIssueParseError::InvalidPackageType(
                            package_type_str.to_string(),
                        ))
                    }
                });
                package = Some(package_str.to_string());
            } else {
                package_type = None;
                package = Some(before.to_string());
            }
            after
        } else {
            package_type = None;
            package = None;
            value
        };
        let mut parts = after.trim().split(' ');
        let tag = parts.next().map(|s| s.to_string());
        let info: Vec<_> = parts.map(|s| s.to_string()).collect();
        let info = if info.is_empty() { None } else { Some(info) };
        Ok(Self {
            package,
            package_type,
            tag,
            info,
        })
    }
}

#[derive(Clone, PartialEq, Eq, Debug, serde::Serialize, serde::Deserialize)]
#[pyo3::pyclass]
pub struct FixerResult {
    pub description: String,
    pub certainty: Option<Certainty>,
    pub patch_name: Option<String>,
    pub revision_id: Option<RevisionId>,
    pub fixed_lintian_issues: Vec<LintianIssue>,
    pub overridden_lintian_issues: Vec<LintianIssue>,
}

impl FixerResult {
    pub fn new(
        description: String,
        fixed_lintian_tags: Option<Vec<String>>,
        certainty: Option<Certainty>,
        patch_name: Option<String>,
        revision_id: Option<RevisionId>,
        mut fixed_lintian_issues: Vec<LintianIssue>,
        overridden_lintian_issues: Option<Vec<LintianIssue>>,
    ) -> Self {
        if let Some(fixed_lintian_tags) = fixed_lintian_tags.as_ref() {
            fixed_lintian_issues.extend(
                fixed_lintian_tags
                    .iter()
                    .map(|tag| LintianIssue::just_tag(tag.to_string())),
            );
        }
        Self {
            description,
            certainty,
            patch_name,
            revision_id,
            fixed_lintian_issues,
            overridden_lintian_issues: overridden_lintian_issues.unwrap_or(vec![]),
        }
    }
    pub fn fixed_lintian_tags(&self) -> Vec<&str> {
        self.fixed_lintian_issues
            .iter()
            .filter_map(|issue| issue.tag.as_deref())
            .collect()
    }
}

#[derive(Clone, PartialEq, Eq, Debug)]
pub enum OutputParseError {
    UnsupportedCertainty(String),
    LintianIssueParseError(LintianIssueParseError),
}

impl std::fmt::Display for OutputParseError {
    fn fmt(&self, f: &mut std::fmt::Formatter) -> std::fmt::Result {
        match self {
            OutputParseError::UnsupportedCertainty(s) => {
                write!(f, "Unsupported certainty: {}", s)
            }
            OutputParseError::LintianIssueParseError(e) => write!(f, "{}", e),
        }
    }
}

impl std::error::Error for OutputParseError {}

impl From<LintianIssueParseError> for OutputParseError {
    fn from(value: LintianIssueParseError) -> Self {
        Self::LintianIssueParseError(value)
    }
}

pub fn parse_script_fixer_output(text: &str) -> Result<FixerResult, OutputParseError> {
    let mut description: Vec<String> = Vec::new();
    let mut overridden_issues: Vec<LintianIssue> = Vec::new();
    let mut fixed_lintian_issues: Vec<LintianIssue> = Vec::new();
    let mut fixed_lintian_tags: Vec<String> = Vec::new();
    let mut certainty: Option<String> = None;
    let mut patch_name: Option<String> = None;

    let lines: Vec<&str> = text.split_terminator('\n').collect();
    let mut i = 0;

    while i < lines.len() {
        if let Some((key, value)) = lines[i].split_once(':') {
            match key.trim() {
                "Fixed-Lintian-Tags" => {
                    fixed_lintian_tags.extend(value.split(',').map(|tag| tag.trim().to_owned()));
                }
                "Fixed-Lintian-Issues" => {
                    i += 1;
                    while i < lines.len() && lines[i].starts_with(' ') {
                        fixed_lintian_issues.push(LintianIssue::try_from(&lines[i][1..])?);
                        i += 1;
                    }
                    continue;
                }
                "Overridden-Lintian-Issues" => {
                    i += 1;
                    while i < lines.len() && lines[i].starts_with(' ') {
                        overridden_issues.push(LintianIssue::try_from(&lines[i][1..])?);
                        i += 1;
                    }
                    continue;
                }
                "Certainty" => {
                    certainty = Some(value.trim().to_owned());
                }
                "Patch-Name" => {
                    patch_name = Some(value.trim().to_owned());
                }
                _ => {
                    description.push(lines[i].to_owned());
                }
            }
        } else {
            description.push(lines[i].to_owned());
        }

        i += 1;
    }

    let certainty = certainty
        .map(|c| c.parse())
        .transpose()
        .map_err(OutputParseError::UnsupportedCertainty)?;

    let fixed_lintian_tags = if fixed_lintian_tags.is_empty() {
        None
    } else {
        Some(fixed_lintian_tags)
    };

    let overridden_issues = if overridden_issues.is_empty() {
        None
    } else {
        Some(overridden_issues)
    };

    Ok(FixerResult::new(
        description.join("\n"),
        fixed_lintian_tags,
        certainty,
        patch_name,
        None,
        fixed_lintian_issues,
        overridden_issues,
    ))
}

pub fn determine_env(
    package: &str,
    current_version: &Version,
    compat_release: &str,
    minimum_certainty: Certainty,
    trust_package: bool,
    allow_reformatting: bool,
    net_access: bool,
    opinionated: bool,
    diligence: i32,
) -> std::collections::HashMap<String, String> {
    let mut env = std::env::vars().collect::<std::collections::HashMap<_, _>>();
    env.insert("DEB_SOURCE".to_owned(), package.to_owned());
    env.insert("CURRENT_VERSION".to_owned(), current_version.to_string());
    env.insert("COMPAT_RELEASE".to_owned(), compat_release.to_owned());
    env.insert(
        "MINIMUM_CERTAINTY".to_owned(),
        minimum_certainty.to_string(),
    );
    env.insert("TRUST_PACKAGE".to_owned(), trust_package.to_string());
    env.insert(
        "REFORMATTING".to_owned(),
        if allow_reformatting {
            "allow"
        } else {
            "disallow"
        }
        .to_owned(),
    );
    env.insert(
        "NET_ACCESS".to_owned(),
        if net_access { "allow" } else { "disallow" }.to_owned(),
    );
    env.insert(
        "OPINIONATED".to_owned(),
        if opinionated { "yes" } else { "no" }.to_owned(),
    );
    env.insert("DILIGENCE".to_owned(), diligence.to_string());
    env
}

/// A fixer script
///
/// The `lintian_tags attribute contains the name of the lintian tags this fixer addresses.
pub trait Fixer: std::fmt::Debug + Sync {
    /// Name of the fixer
    fn name(&self) -> String;

    /// Path to the fixer script
    fn path(&self) -> std::path::PathBuf;

    /// Lintian tags this fixer addresses
    fn lintian_tags(&self) -> Vec<String>;

    /// Apply this fixer script.
    ///
    /// # Arguments
    ///
    /// * `basedir` - Directory in which to run
    /// * `package` - Name of the source package
    /// * `current_version` - The version of the package that is being created or updated
    /// * `compat_release` - Compatibility level (a Debian release name)
    /// * `minimum_certainty` - Minimum certainty level
    /// * `trust_package` - Whether to run code from the package
    /// * `allow_reformatting` - Allow reformatting of files that are being changed
    /// * `net_access` - Allow network access
    /// * `opinionated` - Whether to be opinionated
    /// * `diligence` - Level of diligence
    ///
    /// # Returns
    ///
    ///  A FixerResult object
    fn run(
        &self,
        basedir: &std::path::Path,
        package: &str,
        current_version: &Version,
        compat_release: &str,
        minimum_certainty: Option<Certainty>,
        trust_package: Option<bool>,
        allow_reformatting: Option<bool>,
        net_access: Option<bool>,
        opinionated: Option<bool>,
        diligence: Option<i32>,
    ) -> Result<FixerResult, FixerError>;
}

/// A fixer that is implemented as a Python script.
///
/// This gets used just for Python scripts, and significantly speeds things up because it prevents
/// starting a new Python interpreter for every fixer.
#[cfg(feature = "python")]
#[derive(Debug)]
pub struct PythonScriptFixer {
    path: std::path::PathBuf,
    name: String,
    lintian_tags: Vec<String>,
}

#[cfg(feature = "python")]
impl PythonScriptFixer {
    pub fn new(name: String, lintian_tags: Vec<String>, path: std::path::PathBuf) -> Self {
        Self {
            path,
            name,
            lintian_tags,
        }
    }
}

#[cfg(feature = "python")]
impl Fixer for PythonScriptFixer {
    fn name(&self) -> String {
        self.name.clone()
    }

    fn path(&self) -> std::path::PathBuf {
        self.path.clone()
    }

    fn lintian_tags(&self) -> Vec<String> {
        self.lintian_tags.clone()
    }

    fn run(
        &self,
        basedir: &std::path::Path,
        package: &str,
        current_version: &Version,
        compat_release: &str,
        minimum_certainty: Option<Certainty>,
        trust_package: Option<bool>,
        allow_reformatting: Option<bool>,
        net_access: Option<bool>,
        opinionated: Option<bool>,
        diligence: Option<i32>,
    ) -> Result<FixerResult, FixerError> {
        let env = determine_env(
            package,
            current_version,
            compat_release,
            minimum_certainty.unwrap_or(Certainty::default()),
            trust_package.unwrap_or(false),
            allow_reformatting.unwrap_or(false),
            net_access.unwrap_or(true),
            opinionated.unwrap_or(false),
            diligence.unwrap_or(0),
        );

        use pyo3::import_exception;
        use pyo3::prelude::*;
        use pyo3::types::PyDict;

        import_exception!(debmutate.reformatting, FormattingUnpreservable);
        import_exception!(debian.changelog, ChangelogCreateError);

        Python::with_gil(|py| {
            let sys = py.import("sys")?;
            let os = py.import("os")?;
            let io = py.import("io")?;
            let fixer_module = py.import("lintian_brush.fixer")?;

            let old_env = os.getattr("environ")?.into_py(py);
            let old_stderr = sys.getattr("stderr")?;
            let old_stdout = sys.getattr("stdout")?;

            sys.setattr("stderr", io.call_method0("StringIO")?)?;
            sys.setattr("stdout", io.call_method0("StringIO")?)?;
            os.setattr("environ", env)?;

            let old_cwd = match os.call_method0("getcwd") {
                Ok(cwd) => Some(cwd),
                Err(_) => None,
            };

            os.call_method1("chdir", (basedir,))?;

            let global_vars = PyDict::new(py);
            global_vars.set_item("__file__", &self.path)?;
            global_vars.set_item("__name__", "__main__")?;

            let code = std::fs::read_to_string(&self.path)
                .map_err(|e| FixerError::Other(format!("Failed to read script: {}", e)))?;

            let script_result = PyModule::from_code(
                py,
                code.as_str(),
                self.path.to_str().unwrap(),
                self.name.as_str(),
            );

            let stdout = sys
                .getattr("stdout")
                .unwrap()
                .call_method0("getvalue")
                .unwrap()
                .extract::<String>()
                .unwrap();

            let mut stderr = sys
                .getattr("stderr")
                .unwrap()
                .call_method0("getvalue")
                .unwrap()
                .extract::<String>()
                .unwrap();

            os.setattr("environ", old_env).unwrap();
            sys.setattr("stderr", old_stderr).unwrap();
            sys.setattr("stdout", old_stdout).unwrap();

            if let Some(cwd) = old_cwd {
                os.call_method1("chdir", (cwd,))?;
            }

            fixer_module.call_method0("reset")?;

            let retcode;
            let description;

            match script_result {
                Ok(_) => {
                    retcode = 0;
                    description = stdout;
                }
                Err(e) => {
                    if e.is_instance_of::<FormattingUnpreservable>(py) {
                        return Err(FixerError::FormattingUnpreservable(
                            e.value(py).getattr("path")?.extract()?,
                        ));
                    } else if e.is_instance_of::<ChangelogCreateError>(py) {
                        return Err(FixerError::ChangelogCreate(
                            e.value(py).get_item(0)?.extract()?,
                        ));
                    } else if e.is_instance_of::<pyo3::exceptions::PyMemoryError>(py) {
                        return Err(FixerError::MemoryError);
                    } else if e.is_instance_of::<pyo3::exceptions::PySystemExit>(py) {
                        retcode = e.value(py).getattr("code")?.extract()?;
                        description = stdout;
                    } else {
                        use pyo3::types::IntoPyDict;
                        let traceback = py.import("traceback")?;
                        let traceback_io = io.call_method0("StringIO")?;
                        let kwargs = [("file", traceback_io)].into_py_dict(py);
                        traceback.call_method(
                            "print_exception",
                            (e.get_type(py), &e, e.traceback(py)),
                            Some(kwargs),
                        )?;
                        let traceback_str =
                            traceback_io.call_method0("getvalue")?.extract::<String>()?;
                        stderr = format!("{}\n{}", stderr, traceback_str);
                        return Err(FixerError::ScriptFailed {
                            path: self.path.clone(),
                            exit_code: 1,
                            stderr,
                        });
                    }
                }
            }

            if retcode == 2 {
                Err(FixerError::NoChanges)
            } else if retcode != 0 {
                Err(FixerError::ScriptFailed {
                    path: self.path.clone(),
                    exit_code: retcode,
                    stderr,
                })
            } else {
                Ok(parse_script_fixer_output(&description)?)
            }
        })
    }
}

#[derive(Debug)]
pub enum FixerError {
    NoChanges,
    NoChangesAfterOverrides(Vec<LintianIssue>),
    NotCertainEnough(Certainty, Option<Certainty>, Vec<LintianIssue>),
    NotDebianPackage(std::path::PathBuf),
    DescriptionMissing,
    ScriptNotFound(std::path::PathBuf),
    OutputParseError(OutputParseError),
    OutputDecodeError(std::string::FromUtf8Error),
    FailedPatchManipulation(std::path::PathBuf, std::path::PathBuf, String),
    ChangelogCreate(String),
    ScriptFailed {
        path: std::path::PathBuf,
        exit_code: i32,
        stderr: String,
    },
    FormattingUnpreservable(std::path::PathBuf),
    #[cfg(feature = "python")]
    Python(pyo3::PyErr),
    MemoryError,
    Other(String),
}

impl From<OutputParseError> for FixerError {
    fn from(e: OutputParseError) -> Self {
        FixerError::OutputParseError(e)
    }
}

#[cfg(feature = "python")]
impl From<pyo3::PyErr> for FixerError {
    fn from(e: pyo3::PyErr) -> Self {
        FixerError::Python(e)
    }
}

impl std::fmt::Display for FixerError {
    fn fmt(&self, f: &mut std::fmt::Formatter) -> std::fmt::Result {
        match self {
            FixerError::NoChanges => write!(f, "No changes"),
            FixerError::NoChangesAfterOverrides(_) => write!(f, "No changes after overrides"),
            FixerError::OutputParseError(e) => write!(f, "Output parse error: {}", e),
            FixerError::OutputDecodeError(e) => write!(f, "Output decode error: {}", e),
            FixerError::ScriptNotFound(p) => write!(f, "Command not found: {}", p.display()),
            FixerError::ChangelogCreate(m) => write!(f, "Changelog create error: {}", m),
            FixerError::FormattingUnpreservable(p) => {
                write!(f, "Formatting unpreservable for {}", p.display())
            }
            FixerError::ScriptFailed {
                path,
                exit_code,
                stderr,
            } => write!(
                f,
                "Script failed: {} (exit code {}) (stderr: {})",
                path.display(),
                exit_code,
                stderr
            ),
            FixerError::Other(s) => write!(f, "{}", s),
            FixerError::Python(e) => write!(f, "{}", e),
            FixerError::NotDebianPackage(p) => write!(f, "Not a Debian package: {}", p.display()),
            FixerError::DescriptionMissing => {
                write!(f, "Description missing")
            }
            FixerError::MemoryError => {
                write!(f, "Memory error")
            }
            FixerError::NotCertainEnough(actual, minimum, _) => write!(
                f,
                "Not certain enough to fix (actual: {}, minimum : {:?})",
                actual, minimum
            ),
            FixerError::FailedPatchManipulation(p, p2, s) => write!(
                f,
                "Failed to manipulate patch {} in {}: {}",
                p.display(),
                p2.display(),
                s
            ),
        }
    }
}

impl std::error::Error for FixerError {}

#[derive(Debug)]
pub struct ScriptFixer {
    path: std::path::PathBuf,
    name: String,
    lintian_tags: Vec<String>,
}

impl ScriptFixer {
    pub fn new(name: String, lintian_tags: Vec<String>, path: std::path::PathBuf) -> Self {
        Self {
            path,
            name,
            lintian_tags,
        }
    }
}

impl Fixer for ScriptFixer {
    fn name(&self) -> String {
        self.name.clone()
    }

    fn path(&self) -> std::path::PathBuf {
        self.path.clone()
    }

    fn lintian_tags(&self) -> Vec<String> {
        self.lintian_tags.clone()
    }

    fn run(
        &self,
        basedir: &std::path::Path,
        package: &str,
        current_version: &Version,
        compat_release: &str,
        minimum_certainty: Option<Certainty>,
        trust_package: Option<bool>,
        allow_reformatting: Option<bool>,
        net_access: Option<bool>,
        opinionated: Option<bool>,
        diligence: Option<i32>,
    ) -> Result<FixerResult, FixerError> {
        let env = determine_env(
            package,
            current_version,
            compat_release,
            minimum_certainty.unwrap_or(Certainty::default()),
            trust_package.unwrap_or(false),
            allow_reformatting.unwrap_or(false),
            net_access.unwrap_or(true),
            opinionated.unwrap_or(false),
            diligence.unwrap_or(0),
        );

        let mut cmd = Command::new(self.path.as_os_str());
        cmd.current_dir(basedir);

        for (key, value) in env.iter() {
            cmd.env(key, value);
        }

        let output = cmd.output().map_err(|e| match e.kind() {
            std::io::ErrorKind::NotFound => FixerError::ScriptNotFound(self.path.clone()),
            _ => FixerError::Other(e.to_string()),
        })?;

        if !output.status.success() {
            let mut stderr = String::new();
            let mut stderr_buf = std::io::BufReader::new(&output.stderr[..]);
            stderr_buf
                .read_to_string(&mut stderr)
                .map_err(|e| FixerError::Other(format!("Failed to read stderr: {}", e)))?;

            if output.status.code() == Some(2) {
                return Err(FixerError::NoChanges);
            }

            return Err(FixerError::ScriptFailed {
                path: self.path.to_owned(),
                exit_code: output.status.code().unwrap(),
                stderr,
            });
        }

        let stdout = String::from_utf8(output.stdout).map_err(FixerError::OutputDecodeError)?;
        parse_script_fixer_output(&stdout).map_err(FixerError::OutputParseError)
    }
}

pub fn read_desc_file<P: AsRef<std::path::Path>>(
    path: P,
    force_subprocess: bool,
) -> Result<impl Iterator<Item = Box<dyn Fixer>>, Box<dyn std::error::Error>> {
    let file = File::open(path.as_ref())?;
    let reader = BufReader::new(file);

    let data: serde_yaml::Sequence = serde_yaml::from_reader(reader)?;

    let dirname = path.as_ref().parent().unwrap().to_owned();
    let fixer_iter = data.into_iter().map(move |item| {
        let script = item.get("script").unwrap().as_str().unwrap().to_string();
        let lintian_tags = item
            .get("lintian-tags")
            .map(|tags| {
                Some(
                    tags.as_sequence()?
                        .iter()
                        .filter_map(|tag| Some(tag.as_str()?.to_owned()))
                        .collect::<Vec<_>>(),
                )
            })
            .unwrap_or_default();
        let name = std::path::Path::new(script.as_str())
            .file_stem()
            .and_then(|name| name.to_str())
            .unwrap_or("");
        let script_path = dirname.join(script.as_str());

        load_fixer(
            name.to_owned(),
            lintian_tags.unwrap_or_default(),
            script_path,
            force_subprocess,
        )
    });

    Ok(fixer_iter)
}

fn load_fixer(
    name: String,
    tags: Vec<String>,
    script_path: std::path::PathBuf,
    force_subprocess: bool,
) -> Box<dyn Fixer> {
    #[cfg(feature = "python")]
    if script_path
        .extension()
        .map(|ext| ext == "py")
        .unwrap_or(false)
        && !force_subprocess
    {
        return Box::new(PythonScriptFixer::new(name, tags, script_path));
    }
    Box::new(ScriptFixer::new(name, tags, script_path))
}

/// Return a list of available lintian fixers.
///
/// # Arguments
///
/// * `fixers_dir` - The directory to search for fixers.
/// * `force_subprocess` - Force the use of a subprocess for all fixers.
pub fn available_lintian_fixers(
    fixers_dir: Option<&std::path::Path>,
    force_subprocess: Option<bool>,
) -> Result<impl Iterator<Item = Box<dyn Fixer>>, Box<dyn std::error::Error>> {
    let system_path = find_fixers_dir();
    let fixers_dir = fixers_dir.unwrap_or_else(|| system_path.as_ref().unwrap().as_path());
    let mut fixers = Vec::new();
    // Scan fixers_dir for .desc files
    for entry in std::fs::read_dir(fixers_dir)? {
        let entry = entry?;
        let path = entry.path();
        if path.is_file() && path.extension().map(|ext| ext == "desc").unwrap_or(false) {
            let fixer_iter = read_desc_file(&path, force_subprocess.unwrap_or(false))?;
            fixers.extend(fixer_iter);
        }
    }

    Ok(fixers.into_iter())
}

#[derive(Debug)]
pub struct UnknownFixer(pub String);

impl std::fmt::Display for UnknownFixer {
    fn fmt(&self, f: &mut std::fmt::Formatter) -> std::fmt::Result {
        write!(f, "Unknown fixer: {}", self.0)
    }
}

impl std::error::Error for UnknownFixer {}

/// """Select fixers by name, from a list.
///
/// # Arguments
///
/// * `fixers` - List of Fixer objects
/// * `names` - Set of names to select
/// * `exclude` - Set of names to exclude
pub fn select_fixers(
    fixers: Vec<Box<dyn Fixer>>,
    names: Option<&[&str]>,
    exclude: Option<&[&str]>,
) -> Result<Vec<Box<dyn Fixer>>, UnknownFixer> {
    let mut select_set = names.map(|names| names.iter().cloned().collect::<HashSet<_>>());
    let mut exclude_set = exclude.map(|exclude| exclude.iter().cloned().collect::<HashSet<_>>());
    let mut ret = vec![];
    for f in fixers.into_iter() {
        if let Some(select_set) = select_set.as_mut() {
            if !select_set.remove(f.name().as_str()) {
                continue;
            }
        }
        if let Some(exclude_set) = exclude_set.as_mut() {
            if exclude_set.remove(f.name().as_str()) {
                continue;
            }
        }
        ret.push(f);
    }
    if select_set.is_some() && !select_set.as_ref().unwrap().is_empty() {
        Err(UnknownFixer(
            select_set.unwrap().iter().next().unwrap().to_string(),
        ))
    } else if select_set.is_some() && !exclude_set.as_ref().unwrap().is_empty() {
        Err(UnknownFixer(
            exclude_set.unwrap().iter().next().unwrap().to_string(),
        ))
    } else {
        Ok(ret)
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

pub mod release_info;

pub const DEFAULT_VALUE_LINTIAN_BRUSH_ADDON_ONLY: i32 = 10;
pub const DEFAULT_VALUE_LINTIAN_BRUSH: i32 = 50;
pub const LINTIAN_BRUSH_TAG_VALUES: [(&str, i32); 1] = [("trailing-whitespace", 0)];
pub const DEFAULT_ADDON_FIXERS: &[&str] = &[
    "debian-changelog-line-too-long",
    "trailing-whitespace",
    "out-of-date-standards-version",
    "package-uses-old-debhelper-compat-version",
    "public-upstream-key-not-minimal",
];
pub const LINTIAN_BRUSH_TAG_DEFAULT_VALUE: i32 = 5;

pub fn calculate_value(tags: &[&str]) -> i32 {
    if tags.is_empty() {
        return 0;
    }

    let default_addon_fixers: HashSet<&str> = DEFAULT_ADDON_FIXERS.iter().cloned().collect();
    let tag_set: HashSet<&str> = tags.iter().cloned().collect();

    if tag_set.is_subset(&default_addon_fixers) {
        return DEFAULT_VALUE_LINTIAN_BRUSH_ADDON_ONLY;
    }

    let mut value = DEFAULT_VALUE_LINTIAN_BRUSH;

    for tag in tags {
        if let Some(tag_value) = LINTIAN_BRUSH_TAG_VALUES.iter().find(|(t, _)| t == tag) {
            value += tag_value.1;
        } else {
            value += LINTIAN_BRUSH_TAG_DEFAULT_VALUE;
        }
    }

    value
}

pub fn data_file_path(
    name: &str,
    check: impl Fn(&std::path::Path) -> bool,
) -> Option<std::path::PathBuf> {
    let mut path = std::path::PathBuf::from(env!("CARGO_MANIFEST_DIR"));
    path = path.join("..").join(name);
    if check(&path) {
        return Some(path);
    }

    use pyo3::Python;
    match Python::with_gil(|py| {
        let pkg_resources = py.import("pkg_resources").unwrap();
        if let Ok(path) = pkg_resources.call_method1(
            "resource_filename",
            ("lintian_brush", format!("lintian-brush/{}", name)),
        ) {
            if let Ok(path) = path.extract::<std::path::PathBuf>() {
                if check(path.as_path()) {
                    return Some(path);
                }
            }
        }
        None
    }) {
        Some(path) => return Some(path),
        None => (),
    }

    let base_paths = &["/usr/share/lintian-brush", "/usr/local/share/lintian-brush"];

    for base_path in base_paths {
        let path = std::path::Path::new(base_path).join(name);
        if check(&path) {
            return Some(path);
        }
    }

    None
}

pub fn find_fixers_dir() -> Option<std::path::PathBuf> {
    data_file_path("fixers", |path| path.is_dir())
}

/// Run a lintian fixer on a tree.
///
/// # Arguments
///
///  * `local_tree`: WorkingTree object
///  * `basis_tree`: Tree
///  * `fixer`: Fixer object to apply
///  * `committer`: Optional committer (name and email)
///  * `update_changelog`: Whether to add a new entry to the changelog
///  * `compat_release`: Minimum release that the package should be usable on
///  * `  (e.g. 'stable' or 'unstable')
///  * `minimum_certainty`: How certain the fixer should be
///  * `  about its changes.
///  * `trust_package`: Whether to run code from the package if necessary
///  * `allow_reformatting`: Whether to allow reformatting of changed files
///  * `dirty_tracker`: Optional object that can be used to tell if the tree
///  * `  has been changed.
///  * `subpath`: Path in tree to operate on
///  * `net_access`: Whether to allow accessing external services
///  * `opinionated`: Whether to be opinionated
///  * `diligence`: Level of diligence
///
/// # Returns
///   tuple with set of FixerResult, summary of the changes
pub fn run_lintian_fixer(
    local_tree: &WorkingTree,
    fixer: &Box<dyn Fixer>,
    committer: Option<&str>,
    mut update_changelog: impl FnMut() -> bool,
    compat_release: Option<&str>,
    minimum_certainty: Option<Certainty>,
    trust_package: Option<bool>,
    allow_reformatting: Option<bool>,
    dirty_tracker: Option<&DirtyTracker>,
    subpath: &std::path::Path,
    net_access: Option<bool>,
    opinionated: Option<bool>,
    diligence: Option<i32>,
    timestamp: Option<chrono::naive::NaiveDateTime>,
    basis_tree: Option<&Box<dyn Tree>>,
    changes_by: Option<&str>,
) -> Result<(FixerResult, String), FixerError> {
    pyo3::Python::with_gil(|py| {
        use pyo3::import_exception;
        import_exception!(breezy.transport, NoSuchFile);
        let mut _bt = None;
        let basis_tree: &Box<dyn Tree> = if let Some(basis_tree) = basis_tree {
            basis_tree
        } else {
            _bt = Some(local_tree.basis_tree());
            _bt.as_ref().unwrap()
        };
        let changes_by = changes_by.unwrap_or("lintian-brush");

        let changelog_path = subpath.join("debian/changelog");

        let r = match local_tree.get_file(changelog_path.as_path()) {
            Ok(f) => f,
            Err(e) if e.is_instance_of::<NoSuchFile>(py) => {
                return Err(FixerError::NotDebianPackage(
                    local_tree.abspath(subpath).unwrap(),
                ));
            }
            Err(e) => return Err(e.into()),
        };

        let cl = debianshim::Changelog::from_reader(r, Some(1))?;
        let package = cl.package();
        let current_version: Version = if cl.distributions() == "UNRELEASED" {
            cl.version()
        } else {
            let mut version = cl.version();
            increment_version(&mut version);
            version
        };

        let compat_release = compat_release.unwrap_or("sid");
        log::debug!("Running fixer {:?}", fixer);
        let mut result = match fixer.run(
            local_tree.abspath(subpath).unwrap().as_path(),
            package.as_str(),
            &current_version,
            compat_release,
            minimum_certainty,
            trust_package,
            allow_reformatting,
            net_access,
            opinionated,
            diligence,
        ) {
            Ok(r) => r,
            Err(e) => {
                reset_tree(local_tree, Some(basis_tree), Some(subpath), dirty_tracker)?;
                return Err(e);
            }
        };
        if let Some(certainty) = result.certainty {
            if !certainty_sufficient(certainty, minimum_certainty) {
                reset_tree(local_tree, Some(&basis_tree), Some(subpath), dirty_tracker)?;
                return Err(FixerError::NotCertainEnough(
                    certainty,
                    minimum_certainty,
                    result.overridden_lintian_issues,
                ));
            }
        }
        let mut specific_files = if let Some(dirty_tracker) = dirty_tracker {
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
                return Err(FixerError::NoChangesAfterOverrides(
                    result.overridden_lintian_issues,
                ));
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
            pyo3::Python::with_gil(|py| {
                let rename_map_m = py.import("breezy.rename_map")?;
                let rename_map = rename_map_m.getattr("RenameMap")?;
                rename_map
                    .call_method1("guess_renames", (basis_tree.obj(), &local_tree.0, false))?;
                Ok::<(), pyo3::PyErr>(())
            })?;
        }

        let specific_files_ref = specific_files
            .as_ref()
            .map(|fs| fs.iter().map(|p| p.as_path()).collect::<Vec<_>>());

        let changes = local_tree
            .iter_changes(
                &basis_tree,
                specific_files_ref.as_deref(),
                Some(false),
                Some(true),
            )?
            .collect::<Result<Vec<_>, _>>()?;

        if local_tree.get_parent_ids()?.len() <= 1 && changes.is_empty() {
            return Err(FixerError::NoChangesAfterOverrides(
                result.overridden_lintian_issues,
            ));
        }

        if result.description.is_empty() {
            reset_tree(local_tree, Some(basis_tree), Some(subpath), dirty_tracker)?;
            return Err(FixerError::DescriptionMissing);
        }

        let lines = result.description.split('\n').collect::<Vec<_>>();
        let mut summary = lines[0].to_string();
        let details = lines
            .iter()
            .skip(1)
            .take_while(|l| !l.is_empty())
            .collect::<Vec<_>>();

        // If there are upstream changes in a non-native package, perhaps
        // export them to debian/patches
        if has_non_debian_changes(changes.as_slice(), subpath)
            && current_version.debian_revision.is_some()
        {
            let (patch_name, updated_specific_files) = match _upstream_changes_to_patch(
                local_tree,
                basis_tree,
                dirty_tracker,
                subpath,
                &result
                    .patch_name
                    .as_deref()
                    .map_or_else(|| fixer.name(), |n| n.to_string()),
                result.description.as_str(),
                timestamp,
            ) {
                Ok(r) => r,
                Err(e) => {
                    reset_tree(local_tree, Some(basis_tree), Some(subpath), dirty_tracker)?;
                    return Err(FixerError::Python(e));
                }
            };

            specific_files = Some(updated_specific_files);

            summary = format!("Add patch {}: {}", patch_name, summary);
        }

        let update_changelog = if only_changes_last_changelog_block(
            local_tree,
            basis_tree,
            changelog_path.as_path(),
            changes.iter(),
        )? {
            // If the script only changed the last entry in the changelog,
            // don't update the changelog
            false
        } else {
            update_changelog()
        };

        if update_changelog {
            let mut entry = vec![summary.as_str()];
            entry.extend(details);

            add_changelog_entry(local_tree, changelog_path.as_path(), entry.as_slice())?;
            if let Some(specific_files) = specific_files.as_mut() {
                specific_files.push(changelog_path);
            }
        }

        let mut description = format!("{}\n", result.description);
        description.push('\n');
        description.push_str(format!("Changes-By: {}\n", changes_by).as_str());
        for tag in result.fixed_lintian_tags() {
            description.push_str(format!("Fixes: lintian: {}\n", tag).as_str());
            description.push_str(
                format!("See-also: https://lintian.debian.org/tags/{}.html\n", tag).as_str(),
            );
        }

        let committer = committer.map_or_else(|| get_committer(local_tree), |c| c.to_string());

        let specific_files_ref = specific_files
            .as_ref()
            .map(|fs| fs.iter().map(|p| p.as_path()).collect::<Vec<_>>());

        let revid = local_tree
            .commit(
                description.as_str(),
                Some(false),
                Some(committer.as_str()),
                specific_files_ref.as_deref(),
            )
            .map_err(|e| match e {
                CommitError::PointlessCommit => FixerError::NoChanges,
                CommitError::Other(e) => FixerError::Python(e),
            })?;
        result.revision_id = Some(revid);

        // TODO(jelmer): Support running sbuild & verify lintian warning is gone?
        Ok((result, summary))
    })
}

#[derive(Debug, serde::Serialize, serde::Deserialize, Clone)]
pub struct ChangelogBehaviour {
    pub update_changelog: bool,
    pub explanation: String,
}

impl From<ChangelogBehaviour> for (bool, String) {
    fn from(b: ChangelogBehaviour) -> Self {
        (b.update_changelog, b.explanation)
    }
}

impl From<&ChangelogBehaviour> for (bool, String) {
    fn from(b: &ChangelogBehaviour) -> Self {
        (b.update_changelog, b.explanation.clone())
    }
}

pub fn determine_update_changelog(
    local_tree: &WorkingTree,
    debian_path: &std::path::Path,
) -> pyo3::PyResult<ChangelogBehaviour> {
    pyo3::Python::with_gil(|py| {
        let m = py.import("lintian_brush")?;
        let f = m.getattr("determine_update_changelog")?;
        let result = f.call1((local_tree.obj(), (debian_path,)))?;

        Ok(ChangelogBehaviour {
            update_changelog: result.getattr("update_changelog")?.extract()?,
            explanation: result.getattr("explanation")?.extract()?,
        })
    })
}

#[derive(Debug)]
pub enum OverallError {
    NotDebianPackage(std::path::PathBuf),
    WorkspaceDirty(std::path::PathBuf),
    ChangelogCreate(String),
    #[cfg(feature = "python")]
    Python(pyo3::PyErr),
}

impl From<pyo3::PyErr> for OverallError {
    fn from(e: pyo3::PyErr) -> Self {
        OverallError::Python(e)
    }
}

impl std::fmt::Display for OverallError {
    fn fmt(&self, f: &mut std::fmt::Formatter) -> std::fmt::Result {
        match self {
            OverallError::NotDebianPackage(path) => {
                write!(f, "Not a Debian package: {}", path.display())
            }
            OverallError::WorkspaceDirty(path) => {
                write!(f, "Workspace is dirty: {}", path.display())
            }
            OverallError::ChangelogCreate(m) => {
                write!(f, "Failed to create changelog entry: {}", m)
            }
            #[cfg(feature = "python")]
            OverallError::Python(e) => write!(f, "{}", e),
        }
    }
}

impl std::error::Error for OverallError {}

/// Run a set of lintian fixers on a tree.
///
/// # Arguments
///
///  * `tree`: The tree to run the fixers on
///  * `fixers`: A set of Fixer objects
///  * `update_changelog`: Whether to add an entry to the changelog
///  * `verbose`: Whether to be verbose
///  * `committer`: Optional committer (name and email)
///  * `compat_release`: Minimum release that the package should be usable on
///       (e.g. 'sid' or 'stretch')
///  * `minimum_certainty`: How certain the fixer should be about its changes.
///  * `trust_package`: Whether to run code from the package if necessary
///  * `allow_reformatting`: Whether to allow reformatting of changed files
///  * `use_inotify`: Use inotify to watch changes (significantly improves
///       performance). Defaults to None (automatic)
///  * `subpath`: Subpath in the tree in which the package lives
///  * `net_access`: Whether to allow network access
///  * `opinionated`: Whether to be opinionated
///  * `diligence`: Level of diligence
///  * `changes_by`: Name of the person making the changes
///
/// # Returns:
///   Tuple with two lists:
///     1. list of tuples with (lintian-tag, certainty, description) of fixers
///        that ran
///     2. dictionary mapping fixer names for fixers that failed to run to the
///        error that occurred
pub fn run_lintian_fixers(
    local_tree: &WorkingTree,
    fixers: &[Box<dyn Fixer>],
    mut update_changelog: Option<impl FnMut() -> bool>,
    verbose: bool,
    committer: Option<&str>,
    compat_release: Option<&str>,
    minimum_certainty: Option<Certainty>,
    trust_package: Option<bool>,
    allow_reformatting: Option<bool>,
    use_inotify: Option<bool>,
    subpath: Option<&std::path::Path>,
    net_access: Option<bool>,
    opinionated: Option<bool>,
    diligence: Option<i32>,
    changes_by: Option<&str>,
) -> Result<ManyResult, OverallError> {
    let subpath = subpath.unwrap_or_else(|| std::path::Path::new(""));
    let mut basis_tree = local_tree.basis_tree();
    check_clean_tree(local_tree, &basis_tree, subpath).map_err(|e| match e {
        breezyshim::workspace::CheckCleanTreeError::WorkspaceDirty(p) => {
            OverallError::WorkspaceDirty(p)
        }
        breezyshim::workspace::CheckCleanTreeError::Python(e) => OverallError::Python(e),
    })?;

    let mut changelog_behaviour = None;

    // If we don't know whether to update the changelog, then find out *once*
    let mut update_changelog = || {
        if let Some(update_changelog) = update_changelog.as_mut() {
            return update_changelog();
        }
        let debian_path = subpath.join("debian");
        let cb = determine_update_changelog(local_tree, debian_path.as_path()).unwrap();
        changelog_behaviour = Some(cb);
        changelog_behaviour.as_ref().unwrap().update_changelog
    };

    let mut ret = ManyResult::new();
    let pb = ProgressBar::new(fixers.len() as u64);
    let mut dirty_tracker = match get_dirty_tracker(local_tree, Some(subpath), use_inotify) {
        Ok(dt) => dt,
        Err(breezyshim::dirty_tracker::Error::TooManyOpenFiles) => {
            log::warn!("Too many open files for inotify, not using it.");
            None
        }
        Err(breezyshim::dirty_tracker::Error::Python(e)) => return Err(e.into()),
    };
    for fixer in fixers {
        pb.set_message(format!("Running fixer {}", fixer.name()));
        // Get now from chrono
        let start = std::time::SystemTime::now();
        if let Some(dirty_tracker) = dirty_tracker.as_mut() {
            dirty_tracker.mark_clean();
        }
        pb.inc(1);
        match run_lintian_fixer(
            local_tree,
            fixer,
            committer,
            &mut update_changelog,
            compat_release,
            minimum_certainty,
            trust_package,
            allow_reformatting,
            dirty_tracker.as_ref(),
            subpath,
            net_access,
            opinionated,
            diligence,
            None,
            Some(&basis_tree),
            changes_by,
        ) {
            Err(e) => match e {
                FixerError::NotDebianPackage(path) => {
                    return Err(OverallError::NotDebianPackage(path));
                }
                FixerError::ChangelogCreate(m) => {
                    return Err(OverallError::ChangelogCreate(m));
                }
                FixerError::OutputParseError(ref _e) => {
                    ret.failed_fixers.insert(fixer.name(), e.to_string());
                    if verbose {
                        log::info!("Fixer {} failed to parse output.", fixer.name());
                    }
                    continue;
                }
                FixerError::DescriptionMissing => {
                    ret.failed_fixers.insert(fixer.name(), e.to_string());
                    if verbose {
                        log::info!(
                            "Fixer {} failed because description is missing.",
                            fixer.name()
                        );
                    }
                    continue;
                }
                FixerError::OutputDecodeError(ref _e) => {
                    ret.failed_fixers.insert(fixer.name(), e.to_string());
                    if verbose {
                        log::info!("Fixer {} failed to decode output.", fixer.name());
                    }
                    continue;
                }
                FixerError::FormattingUnpreservable(path) => {
                    ret.formatting_unpreservable
                        .insert(fixer.name(), path.clone());
                    if verbose {
                        log::info!(
                            "Fixer {} was unable to preserve formatting of {}.",
                            fixer.name(),
                            path.display()
                        );
                    }
                    continue;
                }
                FixerError::ScriptNotFound(ref p) => {
                    ret.failed_fixers.insert(fixer.name(), e.to_string());
                    if verbose {
                        log::info!("Fixer {} ({}) not found.", fixer.name(), p.display());
                    }
                    continue;
                }
                FixerError::ScriptFailed { .. } => {
                    ret.failed_fixers.insert(fixer.name(), e.to_string());
                    if verbose {
                        log::info!("Fixer {} failed to run.", fixer.name());
                        eprintln!("{}", e);
                    }
                    continue;
                }
                FixerError::MemoryError => {
                    ret.failed_fixers.insert(fixer.name(), e.to_string());
                    if verbose {
                        log::info!("Ran out of memory while running fixer {}.", fixer.name());
                    }
                    continue;
                }
                FixerError::NotCertainEnough(actual_certainty, minimum_certainty, _overrides) => {
                    if verbose {
                        let duration = std::time::SystemTime::now().duration_since(start).unwrap();
                        log::info!(
                    "Fixer {} made changes but not high enough certainty (was {}, needed {}). (took: {:2}s)",
                    fixer.name(),
                    actual_certainty,
                    minimum_certainty.map_or("default".to_string(), |c| c.to_string()),
                    duration.as_secs_f32(),
                );
                    }
                    continue;
                }
                FixerError::FailedPatchManipulation(
                    ref _tree_path,
                    ref _patches_directory,
                    ref reason,
                ) => {
                    if verbose {
                        log::info!("Unable to manipulate upstream patches: {}", reason);
                    }
                    ret.failed_fixers.insert(fixer.name(), e.to_string());
                    continue;
                }
                FixerError::NoChanges => {
                    if verbose {
                        let duration = std::time::SystemTime::now().duration_since(start).unwrap();
                        log::info!(
                            "Fixer {} made no changes. (took: {:2}s)",
                            fixer.name(),
                            duration.as_secs_f32(),
                        );
                    }
                    continue;
                }
                FixerError::NoChangesAfterOverrides(os) => {
                    if verbose {
                        let duration = std::time::SystemTime::now().duration_since(start).unwrap();
                        log::info!(
                            "Fixer {} made no changes. (took: {:2}s)",
                            fixer.name(),
                            duration.as_secs_f32(),
                        );
                    }
                    ret.overridden_lintian_issues.extend(os);
                    continue;
                }
                FixerError::Python(ref ep) => {
                    if verbose {
                        log::info!("Fixer {} failed: {}", fixer.name(), ep);
                    }
                    ret.failed_fixers.insert(fixer.name(), e.to_string());
                    continue;
                }
                FixerError::Other(ref em) => {
                    if verbose {
                        log::info!("Fixer {} failed: {}", fixer.name(), em);
                    }
                    ret.failed_fixers.insert(fixer.name(), e.to_string());
                    continue;
                }
            },
            Ok((result, summary)) => {
                if verbose {
                    let duration = std::time::SystemTime::now().duration_since(start).unwrap();
                    log::info!(
                        "Fixer {} made changes. (took {:2}s)",
                        fixer.name(),
                        duration.as_secs_f32(),
                    );
                }
                ret.success.push((result, summary));
                basis_tree = local_tree.basis_tree();
            }
        }
    }
    pb.finish();
    ret.changelog_behaviour = changelog_behaviour;
    Ok(ret)
}

fn add_changelog_entry(
    working_tree: &WorkingTree,
    changelog_path: &std::path::Path,
    entry: &[&str],
) -> pyo3::PyResult<()> {
    pyo3::Python::with_gil(|py| {
        let changelog_m = py.import("lintian_brush.changelog")?;
        let add_changelog_entry = changelog_m.getattr("add_changelog_entry")?;

        add_changelog_entry.call1((&working_tree.0, changelog_path, entry.to_vec()))?;
        Ok(())
    })
}

/// Check whether the only change in a tree is to the last changelog entry.
///
/// # Arguments
/// * `tree`: Tree to analyze
/// * `changelog_path`: Path to the changelog file
/// * `changes`: Changes in the tree
pub fn only_changes_last_changelog_block<'a>(
    tree: &WorkingTree,
    basis_tree: &Box<dyn Tree>,
    changelog_path: &std::path::Path,
    changes: impl Iterator<Item = &'a TreeChange>,
) -> pyo3::PyResult<bool> {
    use pyo3::import_exception;
    import_exception!(breezy.transport, NoSuchFile);
    pyo3::Python::with_gil(|py| {
        let read_lock = tree.lock_read();
        let basis_lock = basis_tree.lock_read();
        let mut changes_seen = false;
        for change in changes {
            if let Some(path) = change.path.1.as_ref() {
                if path == std::path::Path::new("") {
                    continue;
                }
                if path == changelog_path {
                    changes_seen = true;
                    continue;
                }
                if !tree.has_versioned_directories() && changelog_path.starts_with(path) {
                    continue;
                }
            }
            return Ok(false);
        }

        if !changes_seen {
            return Ok(false);
        }
        let new_cl = match basis_tree.get_file(changelog_path) {
            Ok(f) => Changelog::from_reader(f, None)?,
            Err(e) if e.is_instance_of::<NoSuchFile>(py) => {
                return Ok(false);
            }
            Err(e) => {
                return Err(e);
            }
        };
        let old_cl = match tree.get_file(changelog_path) {
            Ok(f) => Changelog::from_reader(f, None)?,
            Err(e) if e.is_instance_of::<NoSuchFile>(py) => {
                return Ok(true);
            }
            Err(e) => {
                return Err(e);
            }
        };
        if old_cl.distributions() != "UNRELEASED" {
            return Ok(false);
        }
        new_cl.pop_first()?;
        old_cl.pop_first()?;
        std::mem::drop(read_lock);
        std::mem::drop(basis_lock);
        println!("{:?} {:?}", new_cl.to_string(), old_cl.to_string());
        Ok(new_cl.to_string() == old_cl.to_string())
    })
}

/// Increment a version number.
///
/// For native packages, increment the main version number.
/// For other packages, increment the debian revision.
///
/// # Arguments
///
///  * `v`: Version to increment (modified in place)
pub fn increment_version(v: &mut Version) {
    if v.debian_revision.is_some() {
        v.debian_revision = v.debian_revision.as_ref().map(|v| {
            {
                regex_replace!(r"\d+$", v, |x: &str| (x.parse::<i32>().unwrap() + 1)
                    .to_string())
            }
            .to_string()
        });
    } else {
        v.upstream_version = regex_replace!(r"\d+$", v.upstream_version.as_ref(), |x: &str| (x
            .parse::<i32>()
            .unwrap()
            + 1)
        .to_string())
        .to_string();
    }
}

#[derive(Debug, Clone, serde::Serialize, serde::Deserialize)]
pub struct ManyResult {
    #[serde(rename = "applied")]
    pub success: Vec<(FixerResult, String)>,
    #[serde(rename = "failed")]
    pub failed_fixers: std::collections::HashMap<String, String>,
    pub changelog_behaviour: Option<ChangelogBehaviour>,
    #[serde(skip)]
    pub overridden_lintian_issues: Vec<LintianIssue>,
    #[serde(skip)]
    pub formatting_unpreservable: std::collections::HashMap<String, std::path::PathBuf>,
}

impl ManyResult {
    pub fn tags_count(&self) -> HashMap<&str, u32> {
        self.success
            .iter()
            .fold(HashMap::new(), |mut acc, (r, _summary)| {
                for tag in r.fixed_lintian_tags() {
                    *acc.entry(tag).or_insert(0) += 1;
                }
                acc
            })
    }

    pub fn value(&self) -> i32 {
        let tags = self
            .success
            .iter()
            .flat_map(|(r, _summary)| r.fixed_lintian_tags())
            .collect::<Vec<_>>();
        calculate_value(tags.as_slice())
    }

    /// Return the minimum certainty of any successfully made change.
    pub fn minimum_success_certainty(&self) -> Option<Certainty> {
        min_certainty(
            self.success
                .iter()
                .filter_map(|(r, _summary)| r.certainty)
                .collect::<Vec<_>>()
                .as_slice(),
        )
    }

    pub fn new() -> Self {
        Self {
            success: Vec::new(),
            failed_fixers: std::collections::HashMap::new(),
            changelog_behaviour: None,
            overridden_lintian_issues: Vec::new(),
            formatting_unpreservable: std::collections::HashMap::new(),
        }
    }
}

fn has_non_debian_changes(changes: &[TreeChange], subpath: &std::path::Path) -> bool {
    let debian_path = subpath.join("debian");
    changes.iter().any(|change| {
        [change.path.0.as_deref(), change.path.1.as_deref()]
            .into_iter()
            .flatten()
            .any(|path| !path.starts_with(&debian_path))
    })
}

pub fn get_committer(working_tree: &WorkingTree) -> String {
    pyo3::Python::with_gil(|py| {
        let m = py.import("lintian_brush")?;
        let get_committer = m.getattr("get_committer")?;
        get_committer.call1((&working_tree.0,))?.extract()
    })
    .unwrap()
}

fn _upstream_changes_to_patch(
    local_tree: &WorkingTree,
    basis_tree: &Box<dyn Tree>,
    dirty_tracker: Option<&DirtyTracker>,
    subpath: &std::path::Path,
    patch_name: &str,
    description: &str,
    timestamp: Option<chrono::naive::NaiveDateTime>,
) -> pyo3::PyResult<(String, Vec<std::path::PathBuf>)> {
    pyo3::Python::with_gil(|py| {
        let m = py.import("lintian_brush")?;
        let upstream_changes_to_patch = m.getattr("_upstream_changes_to_patch")?;
        upstream_changes_to_patch
            .call1((
                &local_tree.0,
                basis_tree.obj(),
                dirty_tracker.map(|dt| &dt.0),
                subpath,
                patch_name,
                description,
                timestamp,
            ))?
            .extract()
    })
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
