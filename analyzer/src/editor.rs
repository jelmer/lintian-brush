use breezyshim::error::Error as BrzError;
use breezyshim::tree::MutableTree;
use std::borrow::Cow;
use std::io::BufRead;
use std::path::PathBuf;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum TemplateType {
    M4,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct GeneratedFile {
    template_path: Option<PathBuf>,
    template_type: Option<TemplateType>,
}

impl std::fmt::Display for GeneratedFile {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(f, "File is generated")?;
        if let Some(template_path) = &self.template_path {
            write!(f, " from {}", template_path.display())?;
        }
        Ok(())
    }
}

impl std::error::Error for GeneratedFile {}

#[derive(Clone, PartialEq, Eq)]
pub struct FormattingUnpreservable {
    original_contents: Option<Vec<u8>>,
    rewritten_contents: Option<Vec<u8>>,
}

impl std::fmt::Debug for FormattingUnpreservable {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.debug_struct("FormattingUnpreservable")
            .field(
                "original_contents",
                &self
                    .original_contents
                    .as_deref()
                    .map(|x| std::str::from_utf8(x)),
            )
            .field(
                "rewritten_contents",
                &self
                    .rewritten_contents
                    .as_deref()
                    .map(|x| std::str::from_utf8(x)),
            )
            .finish()
    }
}

impl std::fmt::Display for FormattingUnpreservable {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(f, "Unable to preserve formatting",)
    }
}

impl std::error::Error for FormattingUnpreservable {}

impl FormattingUnpreservable {
    pub fn diff(&self) -> Vec<String> {
        let original_lines = std::str::from_utf8(self.original_contents.as_deref().unwrap_or(b""))
            .unwrap()
            .split_inclusive('\n')
            .collect::<Vec<_>>();
        let rewritten_lines =
            std::str::from_utf8(self.rewritten_contents.as_deref().unwrap_or(b""))
                .unwrap()
                .split_inclusive('\n')
                .collect::<Vec<_>>();

        difflib::unified_diff(
            original_lines.as_slice(),
            rewritten_lines.as_slice(),
            "original",
            "rewritten",
            "",
            "",
            3,
        )
    }
}

/// Check that formatting can be preserved.
///
/// # Arguments
/// * `rewritten_text` - The rewritten file contents
/// * `text` - The original file contents
/// * `allow_reformatting` - Whether to allow reformatting
fn check_preserve_formatting(
    rewritten_text: Option<&[u8]>,
    text: Option<&[u8]>,
    allow_reformatting: bool,
) -> Result<(), FormattingUnpreservable> {
    if rewritten_text == text {
        return Ok(());
    }
    if allow_reformatting {
        return Ok(());
    }
    Err(FormattingUnpreservable {
        original_contents: text.map(|x| x.to_vec()),
        rewritten_contents: rewritten_text.map(|x| x.to_vec()),
    })
}

pub const DO_NOT_EDIT_SCAN_LINES: usize = 20;

fn check_generated_contents(bufread: &mut dyn BufRead) -> Result<(), GeneratedFile> {
    for l in bufread.lines().take(DO_NOT_EDIT_SCAN_LINES) {
        let l = if let Ok(l) = l { l } else { continue };
        if l.contains("DO NOT EDIT")
            || l.contains("Do not edit!")
            || l.contains("This file is autogenerated")
        {
            return Err(GeneratedFile {
                template_path: None,
                template_type: None,
            });
        }
    }
    Ok(())
}

pub const GENERATED_EXTENSIONS: &[&str] = &["in", "m4", "stub"];

/// Check if a file is generated from another file.
///
/// # Arguments
/// * `path` - Path to the file to check
///
/// # Errors
/// * `GeneratedFile` - when a generated file is found
pub fn check_generated_file(path: &std::path::Path) -> Result<(), GeneratedFile> {
    for ext in GENERATED_EXTENSIONS {
        let template_path = path.with_extension(ext);
        if template_path.exists() {
            return Err(GeneratedFile {
                template_path: Some(template_path),
                template_type: match ext {
                    &"m4" => Some(TemplateType::M4),
                    _ => None,
                },
            });
        }
    }

    match std::fs::File::open(path) {
        Ok(f) => {
            let mut buf = std::io::BufReader::new(f);
            check_generated_contents(&mut buf)?;
        }
        Err(e) if e.kind() == std::io::ErrorKind::NotFound => {}
        Err(e) => panic!("Error reading file: {}", e),
    }
    Ok(())
}

/// Check if a file is generated from another file.
///
/// # Arguments
/// * `path` - Path to the file to check
///
/// # Errors
/// * `GeneratedFile` - when a generated file is found
pub fn tree_check_generated_file(
    tree: &dyn MutableTree,
    path: &std::path::Path,
) -> Result<(), GeneratedFile> {
    for ext in GENERATED_EXTENSIONS {
        let template_path = path.with_extension(ext);
        if tree.has_filename(&template_path) {
            return Err(GeneratedFile {
                template_path: Some(template_path),
                template_type: match ext {
                    &"m4" => Some(TemplateType::M4),
                    _ => None,
                },
            });
        }
    }

    match tree.get_file(&path) {
        Ok(f) => {
            let mut buf = std::io::BufReader::new(f);
            check_generated_contents(&mut buf)?;
        }
        Err(BrzError::NoSuchFile(..)) => {}
        Err(e) => panic!("Error reading file: {}", e),
    }
    Ok(())
}

#[derive(Debug)]
pub enum EditorError {
    GeneratedFile(PathBuf, GeneratedFile),
    FormattingUnpreservable(PathBuf, FormattingUnpreservable),
    IoError(std::io::Error),
    BrzError(BrzError),
}

impl From<BrzError> for EditorError {
    fn from(e: BrzError) -> Self {
        EditorError::BrzError(e)
    }
}

impl std::fmt::Display for EditorError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            EditorError::GeneratedFile(p, e) => {
                write!(f, "File {} is generated from another file", p.display())
            }
            EditorError::FormattingUnpreservable(p, e) => {
                write!(f, "Unable to preserve formatting in {}", p.display())
            }
            EditorError::IoError(e) => write!(f, "I/O error: {}", e),
            EditorError::BrzError(e) => write!(f, "Breezy error: {}", e),
        }
    }
}

impl std::error::Error for EditorError {}

impl From<std::io::Error> for EditorError {
    fn from(e: std::io::Error) -> Self {
        EditorError::IoError(e)
    }
}

#[cfg(feature = "merge3")]
fn update_with_merge3(
    original_contents: &[u8],
    rewritten_contents: &[u8],
    updated_contents: &[u8],
) -> Option<Vec<u8>> {
    let rewritten_lines = rewritten_contents
        .split_inclusive(|&x| x == b'\n')
        .collect::<Vec<_>>();
    let original_lines = original_contents
        .split_inclusive(|&x| x == b'\n')
        .collect::<Vec<_>>();
    let updated_lines = updated_contents
        .split_inclusive(|&x| x == b'\n')
        .collect::<Vec<_>>();
    let m3 = merge3::Merge3::new(
        rewritten_lines.as_slice(),
        original_lines.as_slice(),
        updated_lines.as_slice(),
    );
    if m3
        .merge_regions()
        .iter()
        .any(|x| matches!(x, merge3::MergeRegion::Conflict { .. }))
    {
        return None;
    }
    Some(
        m3.merge_lines(false, &merge3::StandardMarkers::default())
            .join(&b"\n"[..]),
    )
}

fn reformat_file<'a>(
    original_contents: Option<&'a [u8]>,
    rewritten_contents: Option<&'a [u8]>,
    updated_contents: Option<&'a [u8]>,
    allow_reformatting: bool,
) -> Result<(Option<Cow<'a, [u8]>>, bool), FormattingUnpreservable> {
    if updated_contents == rewritten_contents || updated_contents == original_contents {
        return Ok((updated_contents.map(Cow::Borrowed), false));
    }
    let mut updated_contents = updated_contents.map(std::borrow::Cow::Borrowed);
    match check_preserve_formatting(rewritten_contents, original_contents, allow_reformatting) {
        Ok(()) => {}
        Err(e) => {
            if rewritten_contents.is_none()
                || original_contents.is_none()
                || updated_contents.is_none()
            {
                return Err(e);
            }
            #[cfg(feature = "merge3")]
            {
                // Run three way merge
                log::debug!("Unable to preserve formatting; falling back to merge3");
                updated_contents = Some(std::borrow::Cow::Owned(
                    if let Some(lines) = update_with_merge3(
                        original_contents.unwrap(),
                        rewritten_contents.unwrap(),
                        updated_contents.unwrap().as_ref(),
                    ) {
                        lines
                    } else {
                        return Err(e);
                    },
                ));
            }
            #[cfg(not(feature = "merge3"))]
            {
                log::debug!("Unable to preserve formatting; merge3 feature not enabled");
                return Err(e);
            }
        }
    }

    Ok((updated_contents, true))
}

/// Edit a formatted file.
///
/// # Arguments
/// * `path` - Path to the file
/// * `original_contents` - The original contents of the file
/// * `rewritten_contents` - The contents rewritten with our parser/serializer
/// * `updated_contents` - Updated contents rewritten with our parser/serializer after changes were
///   made
/// * `allow_generated` - Do not raise `GeneratedFile` when encountering a generated file
/// * `allow_reformatting` - Whether to allow reformatting of the file
///
/// # Returns
/// `true` if the file was changed, `false` otherwise
pub fn edit_formatted_file(
    path: &std::path::Path,
    original_contents: Option<&[u8]>,
    rewritten_contents: Option<&[u8]>,
    updated_contents: Option<&[u8]>,
    allow_generated: bool,
    allow_reformatting: bool,
) -> Result<bool, EditorError> {
    if !allow_generated {
        check_generated_file(path)
            .map_err(|e| EditorError::GeneratedFile(path.to_path_buf(), e))?;
    }

    let (updated_contents, changed) = reformat_file(
        original_contents,
        rewritten_contents,
        updated_contents,
        allow_reformatting,
    )
    .map_err(|e| EditorError::FormattingUnpreservable(path.to_path_buf(), e))?;
    if changed {
        if let Some(updated_contents) = updated_contents {
            std::fs::write(path, updated_contents)?;
        } else {
            std::fs::remove_file(path)?;
        }
    }
    Ok(changed)
}

/// Edit a formatted file in a tree.
///
/// # Arguments
/// * `tree` - The tree to edit
/// * `path` - Path to the file
/// * `original_contents` - The original contents of the file
/// * `rewritten_contents` - The contents rewritten with our parser/serializer
/// * `updated_contents` - Updated contents rewritten with our parser/serializer after changes were
///   made
/// * `allow_generated` - Do not raise `GeneratedFile` when encountering a generated file
/// * `allow_reformatting` - Whether to allow reformatting of the file
///
/// # Returns
/// `true` if the file was changed, `false` otherwise
pub fn tree_edit_formatted_file(
    tree: &dyn MutableTree,
    path: &std::path::Path,
    original_contents: Option<&[u8]>,
    rewritten_contents: Option<&[u8]>,
    updated_contents: Option<&[u8]>,
    allow_generated: bool,
    allow_reformatting: bool,
) -> Result<bool, EditorError> {
    if !allow_generated {
        tree_check_generated_file(tree, path)
            .map_err(|e| EditorError::GeneratedFile(path.to_path_buf(), e))?;
    }

    let (updated_contents, changed) = reformat_file(
        original_contents,
        rewritten_contents,
        updated_contents,
        allow_reformatting,
    )
    .map_err(|e| EditorError::FormattingUnpreservable(path.to_path_buf(), e))?;
    if changed {
        if let Some(updated_contents) = updated_contents {
            tree.put_file_bytes_non_atomic(path, updated_contents.as_ref())?;
            tree.add(&[path])?;
        } else {
            tree.remove(&[path])?;
        }
    }
    Ok(changed)
}

pub trait Marshallable {
    fn from_bytes(content: &[u8]) -> Self;
    fn missing() -> Self;
    fn to_bytes(&self) -> Option<Vec<u8>>;
}

pub trait Editor<P: Marshallable>:
    std::ops::Deref<Target = P> + std::ops::DerefMut<Target = P>
{
    fn updated_content(&self) -> Option<Vec<u8>>;
    fn rewritten_content(&self) -> Option<&[u8]>;

    fn has_changed(&self) -> bool {
        self.updated_content().as_deref() != self.rewritten_content()
    }

    fn commit(&self) -> Result<Vec<&std::path::Path>, EditorError>;
}

// Allow calling .edit_file("debian/control") on a tree
pub trait MutableTreeEdit {
    fn edit_file<P: Marshallable>(
        &self,
        path: &std::path::Path,
        allow_generated: bool,
        allow_reformatting: bool,
    ) -> Result<TreeEditor<P>, EditorError>;
}

impl<T: MutableTree> MutableTreeEdit for T {
    fn edit_file<P: Marshallable>(
        &self,
        path: &std::path::Path,
        allow_generated: bool,
        allow_reformatting: bool,
    ) -> Result<TreeEditor<P>, EditorError> {
        TreeEditor::new(self, path, allow_generated, allow_reformatting)
    }
}

pub struct TreeEditor<'a, P: Marshallable> {
    tree: &'a dyn MutableTree,
    path: PathBuf,
    orig_content: Option<Vec<u8>>,
    rewritten_content: Option<Vec<u8>>,
    allow_generated: bool,
    allow_reformatting: bool,
    parsed: Option<P>,
}

impl<'a, P: Marshallable> std::ops::Deref for TreeEditor<'a, P> {
    type Target = P;

    fn deref(&self) -> &Self::Target {
        self.parsed.as_ref().unwrap()
    }
}

impl<'a, P: Marshallable> std::ops::DerefMut for TreeEditor<'a, P> {
    fn deref_mut(&mut self) -> &mut Self::Target {
        self.parsed.as_mut().unwrap()
    }
}

impl<'a, P: Marshallable> TreeEditor<'a, P> {
    pub fn from_env(
        tree: &'a dyn MutableTree,
        path: &std::path::Path,
        allow_generated: bool,
        allow_reformatting: Option<bool>,
    ) -> Result<Self, EditorError> {
        let allow_reformatting = allow_reformatting.unwrap_or_else(|| {
            std::env::var("REFORMATTING").unwrap_or("disallow".to_string()) == "allow"
        });

        Self::new(tree, path, allow_generated, allow_reformatting)
    }

    /// Read the file contents and parse them
    fn read(&mut self) -> Result<(), EditorError> {
        self.orig_content = match self.tree.get_file_text(&self.path) {
            Ok(c) => Some(c),
            Err(BrzError::NoSuchFile(..)) => None,
            Err(e) => return Err(e.into()),
        };
        self.parsed = match self.orig_content.as_deref() {
            Some(content) => Some(P::from_bytes(content)),
            None => Some(P::missing()),
        };
        self.rewritten_content = self.orig_content.clone();
        Ok(())
    }

    pub fn new(
        tree: &'a dyn MutableTree,
        path: &std::path::Path,
        allow_generated: bool,
        allow_reformatting: bool,
    ) -> Result<Self, EditorError> {
        let mut ret = Self {
            tree,
            path: path.to_path_buf(),
            orig_content: None,
            rewritten_content: None,
            allow_generated,
            allow_reformatting,
            parsed: None,
        };
        ret.read()?;
        Ok(ret)
    }
}

impl<'a, P: Marshallable> Editor<P> for TreeEditor<'a, P> {
    fn updated_content(&self) -> Option<Vec<u8>> {
        self.parsed.as_ref().unwrap().to_bytes()
    }

    fn rewritten_content(&self) -> Option<&[u8]> {
        self.rewritten_content.as_deref()
    }

    fn commit(&self) -> Result<Vec<&std::path::Path>, EditorError> {
        let updated_content = self.updated_content();

        let changed = edit_formatted_file(
            &self.path,
            self.orig_content.as_deref(),
            self.rewritten_content.as_deref(),
            updated_content.as_deref(),
            self.allow_generated,
            self.allow_reformatting,
        )?;
        if changed {
            Ok(vec![&self.path])
        } else {
            Ok(vec![])
        }
    }
}

pub struct FsEditor<P: Marshallable> {
    path: PathBuf,
    orig_content: Option<Vec<u8>>,
    rewritten_content: Option<Vec<u8>>,
    allow_generated: bool,
    allow_reformatting: bool,
    parsed: Option<P>,
}

impl<M: Marshallable> std::ops::Deref for FsEditor<M> {
    type Target = M;

    fn deref(&self) -> &Self::Target {
        self.parsed.as_ref().unwrap()
    }
}

impl<M: Marshallable> std::ops::DerefMut for FsEditor<M> {
    fn deref_mut(&mut self) -> &mut Self::Target {
        self.parsed.as_mut().unwrap()
    }
}

impl<P: Marshallable> FsEditor<P> {
    pub fn from_env(
        path: &std::path::Path,
        allow_generated: bool,
        allow_reformatting: Option<bool>,
    ) -> Result<Self, EditorError> {
        let allow_reformatting = allow_reformatting.unwrap_or_else(|| {
            std::env::var("REFORMATTING").unwrap_or("disallow".to_string()) == "allow"
        });

        Self::new(path, allow_generated, allow_reformatting)
    }

    /// Read the file contents and parse them
    fn read(&mut self) -> Result<(), EditorError> {
        self.orig_content = match std::fs::read(&self.path) {
            Ok(c) => Some(c),
            Err(e) if e.kind() == std::io::ErrorKind::NotFound => None,
            Err(e) => return Err(e.into()),
        };
        self.parsed = match self.orig_content.as_deref() {
            Some(content) => Some(P::from_bytes(content)),
            None => Some(P::missing()),
        };
        self.rewritten_content = self.orig_content.clone();
        Ok(())
    }

    pub fn new(
        path: &std::path::Path,
        allow_generated: bool,
        allow_reformatting: bool,
    ) -> Result<Self, EditorError> {
        let mut ret = Self {
            path: path.to_path_buf(),
            orig_content: None,
            rewritten_content: None,
            allow_generated,
            allow_reformatting,
            parsed: None,
        };
        ret.read()?;
        Ok(ret)
    }
}

impl<P: Marshallable> Editor<P> for FsEditor<P> {
    fn updated_content(&self) -> Option<Vec<u8>> {
        self.parsed.as_ref().unwrap().to_bytes()
    }

    fn rewritten_content(&self) -> Option<&[u8]> {
        self.rewritten_content.as_deref()
    }

    fn commit(&self) -> Result<Vec<&std::path::Path>, EditorError> {
        let updated_content = self.updated_content();

        let changed = edit_formatted_file(
            &self.path,
            self.orig_content.as_deref(),
            self.rewritten_content.as_deref(),
            updated_content.as_deref(),
            self.allow_generated,
            self.allow_reformatting,
        )?;
        if changed {
            Ok(vec![&self.path])
        } else {
            Ok(vec![])
        }
    }
}

impl Marshallable for debian_control::Control {
    fn from_bytes(content: &[u8]) -> Self {
        debian_control::Control::read_relaxed(std::io::Cursor::new(content))
            .unwrap()
            .0
    }

    fn missing() -> Self {
        debian_control::Control::new()
    }

    fn to_bytes(&self) -> Option<Vec<u8>> {
        self.source()?;
        Some(self.to_string().into_bytes())
    }
}

impl Marshallable for debian_changelog::ChangeLog {
    fn from_bytes(content: &[u8]) -> Self {
        debian_changelog::ChangeLog::read_relaxed(std::io::Cursor::new(content)).unwrap()
    }

    fn missing() -> Self {
        debian_changelog::ChangeLog::new()
    }

    fn to_bytes(&self) -> Option<Vec<u8>> {
        Some(self.to_string().into_bytes())
    }
}

impl Marshallable for debian_copyright::Copyright {
    fn from_bytes(content: &[u8]) -> Self {
        debian_copyright::Copyright::from_str_relaxed(std::str::from_utf8(content).unwrap())
            .unwrap()
            .0
    }

    fn missing() -> Self {
        debian_copyright::Copyright::new()
    }

    fn to_bytes(&self) -> Option<Vec<u8>> {
        Some(self.to_string().into_bytes())
    }
}

impl Marshallable for makefile_lossless::Makefile {
    fn from_bytes(content: &[u8]) -> Self {
        makefile_lossless::Makefile::read_relaxed(std::io::Cursor::new(content)).unwrap()
    }

    fn missing() -> Self {
        makefile_lossless::Makefile::new()
    }

    fn to_bytes(&self) -> Option<Vec<u8>> {
        Some(self.to_string().into_bytes())
    }
}

impl Marshallable for deb822_lossless::Deb822 {
    fn from_bytes(content: &[u8]) -> Self {
        deb822_lossless::Deb822::read_relaxed(std::io::Cursor::new(content)).unwrap().0
    }

    fn missing() -> Self {
        deb822_lossless::Deb822::new()
    }

    fn to_bytes(&self) -> Option<Vec<u8>> {
        Some(self.to_string().into_bytes())
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn test_formatting_same() {
        assert_eq!(
            Ok(()),
            check_preserve_formatting(Some(b"FOO  "), Some(b"FOO  "), false)
        );
    }

    #[test]
    fn test_formatting_different() {
        assert_eq!(
            Err(FormattingUnpreservable {
                original_contents: Some("FOO \n".as_bytes().to_vec()),
                rewritten_contents: Some("FOO  \n".as_bytes().to_vec()),
            }),
            check_preserve_formatting(Some(b"FOO  \n"), Some(b"FOO \n"), false)
        );
    }

    #[test]
    fn test_diff() {
        let e = FormattingUnpreservable {
            original_contents: Some(b"FOO X\n".to_vec()),
            rewritten_contents: Some(b"FOO  X\n".to_vec()),
        };
        assert_eq!(
            e.diff(),
            vec![
                "--- original\t\n",
                "+++ rewritten\t\n",
                "@@ -1 +1 @@\n",
                "-FOO X\n",
                "+FOO  X\n",
            ]
        );
    }

    #[test]
    fn test_reformatting_allowed() {
        assert_eq!(
            Ok(()),
            check_preserve_formatting(Some(b"FOO  "), Some(b"FOO "), true)
        );
    }

    #[test]
    fn test_generated_control_file() {
        let td = tempfile::tempdir().unwrap();
        std::fs::create_dir(td.path().join("debian")).unwrap();
        std::fs::write(td.path().join("debian/control.in"), "Source: blah\n").unwrap();
        assert_eq!(
            Err(GeneratedFile {
                template_path: Some(td.path().join("debian/control.in")),
                template_type: None,
            }),
            check_generated_file(&td.path().join("debian/control"))
        );
    }

    #[test]
    fn test_generated_file_missing() {
        let td = tempfile::tempdir().unwrap();
        std::fs::create_dir(td.path().join("debian")).unwrap();
        assert_eq!(
            Ok(()),
            check_generated_file(&td.path().join("debian/control"))
        );
    }

    #[test]
    fn test_do_not_edit() {
        let td = tempfile::tempdir().unwrap();
        std::fs::create_dir(td.path().join("debian")).unwrap();
        std::fs::write(
            td.path().join("debian/control"),
            "# DO NOT EDIT\nSource: blah\n",
        )
        .unwrap();
        assert_eq!(
            Err(GeneratedFile {
                template_path: None,
                template_type: None,
            }),
            check_generated_file(&td.path().join("debian/control"))
        );
    }

    #[test]
    fn test_do_not_edit_after_header() {
        // check_generated_file() only checks the first 20 lines.
        let td = tempfile::tempdir().unwrap();
        std::fs::create_dir(td.path().join("debian")).unwrap();
        std::fs::write(
            td.path().join("debian/control"),
            "\n".repeat(50) + "# DO NOT EDIT\nSource: blah\n",
        )
        .unwrap();
        assert_eq!(
            Ok(()),
            check_generated_file(&td.path().join("debian/control"))
        );
    }

    #[test]
    fn test_unchanged() {
        let td = tempfile::tempdir().unwrap();
        std::fs::write(td.path().join("a"), "some content\n").unwrap();
        assert!(!edit_formatted_file(
            &td.path().join("a"),
            Some("some content\n".as_bytes()),
            Some("some content reformatted\n".as_bytes()),
            Some("some content\n".as_bytes()),
            false,
            false
        )
        .unwrap());
        assert!(!edit_formatted_file(
            &td.path().join("a"),
            Some("some content\n".as_bytes()),
            Some("some content\n".as_bytes()),
            Some("some content\n".as_bytes()),
            false,
            false
        )
        .unwrap());
        assert!(!edit_formatted_file(
            &td.path().join("a"),
            Some("some content\n".as_bytes()),
            Some("some content reformatted\n".as_bytes()),
            Some("some content reformatted\n".as_bytes()),
            false,
            false
        )
        .unwrap());
    }

    #[test]
    fn test_changed() {
        let td = tempfile::tempdir().unwrap();
        std::fs::write(td.path().join("a"), "some content\n").unwrap();
        assert!(edit_formatted_file(
            &td.path().join("a"),
            Some("some content\n".as_bytes()),
            Some("some content\n".as_bytes()),
            Some("new content\n".as_bytes()),
            false,
            false
        )
        .unwrap());
        assert_eq!(
            "new content\n",
            std::fs::read_to_string(td.path().join("a")).unwrap()
        );
    }

    #[test]
    fn test_unformattable() {
        let td = tempfile::tempdir().unwrap();
        assert!(matches!(
            edit_formatted_file(
                &td.path().join("a"),
                Some(b"some content\n"),
                Some(b"reformatted content\n"),
                Some(b"new content\n"),
                false,
                false
            )
            .unwrap_err(),
            EditorError::FormattingUnpreservable(_, FormattingUnpreservable { .. })
        ));
    }

    struct TestMarshall {
        data: Option<usize>,
    }

    impl TestMarshall {
        fn get_data(&self) -> Option<usize> {
            self.data
        }

        fn unset_data(&mut self) {
            self.data = None;
        }

        fn inc_data(&mut self) {
            match &mut self.data {
                Some(x) => *x += 1,
                None => self.data = Some(1),
            }
        }
    }

    impl Marshallable for TestMarshall {
        fn from_bytes(content: &[u8]) -> Self {
            let data = std::str::from_utf8(content).unwrap().parse().unwrap();
            Self { data: Some(data) }
        }

        fn missing() -> Self {
            Self { data: None }
        }

        fn to_bytes(&self) -> Option<Vec<u8>> {
            self.data.map(|x| x.to_string().into_bytes())
        }
    }

    #[test]
    fn test_edit_create_file() {
        let td = tempfile::tempdir().unwrap();

        let mut editor = FsEditor::<TestMarshall>::new(&td.path().join("a"), false, false).unwrap();
        assert!(!editor.has_changed());
        editor.inc_data();
        assert_eq!(editor.get_data(), Some(1));
        assert!(editor.has_changed());
        assert_eq!(editor.commit().unwrap(), vec![&td.path().join("a")]);
        assert_eq!(editor.get_data(), Some(1));

        assert_eq!("1", std::fs::read_to_string(td.path().join("a")).unwrap());
    }

    #[test]
    fn test_edit_create_no_changes() {
        let td = tempfile::tempdir().unwrap();

        let editor = FsEditor::<TestMarshall>::new(&td.path().join("a"), false, false).unwrap();
        assert!(!editor.has_changed());
        assert_eq!(editor.commit().unwrap(), Vec::<&std::path::Path>::new());
        assert_eq!(editor.get_data(), None);
        assert!(!td.path().join("a").exists());
    }

    #[test]
    fn test_edit_change() {
        let td = tempfile::tempdir().unwrap();
        std::fs::write(td.path().join("a"), "1").unwrap();

        let mut editor = FsEditor::<TestMarshall>::new(&td.path().join("a"), false, false).unwrap();
        assert!(!editor.has_changed());
        editor.inc_data();
        assert_eq!(editor.get_data(), Some(2));
        assert!(editor.has_changed());
        assert_eq!(editor.commit().unwrap(), vec![&td.path().join("a")]);
        assert_eq!(editor.get_data(), Some(2));

        assert_eq!("2", std::fs::read_to_string(td.path().join("a")).unwrap());
    }

    #[test]
    fn test_edit_delete() {
        let td = tempfile::tempdir().unwrap();
        std::fs::write(td.path().join("a"), "1").unwrap();

        let mut editor = FsEditor::<TestMarshall>::new(&td.path().join("a"), false, false).unwrap();
        assert!(!editor.has_changed());
        editor.unset_data();
        assert_eq!(editor.get_data(), None);
        assert!(editor.has_changed());
        assert_eq!(editor.commit().unwrap(), vec![&td.path().join("a")]);
        assert_eq!(editor.get_data(), None);

        assert!(!td.path().join("a").exists());
    }

    #[test]
    fn test_tree_editor_edit() {
        use breezyshim::controldir::{create_standalone_workingtree, ControlDirFormat};
        let tempdir = tempfile::tempdir().unwrap();

        let tree =
            create_standalone_workingtree(tempdir.path(), &ControlDirFormat::default()).unwrap();

        let mut editor = tree
            .edit_file::<TestMarshall>(&tempdir.path().join("a"), false, false)
            .unwrap();

        assert!(!editor.has_changed());
        editor.inc_data();
        assert_eq!(editor.get_data(), Some(1));
        assert!(editor.has_changed());
        assert_eq!(editor.commit().unwrap(), vec![&tempdir.path().join("a")]);

        assert_eq!(
            "1",
            std::fs::read_to_string(tempdir.path().join("a")).unwrap()
        );
    }

    #[test]
    fn test_tree_edit_control() {
        use breezyshim::controldir::{create_standalone_workingtree, ControlDirFormat};
        let tempdir = tempfile::tempdir().unwrap();

        let tree =
            create_standalone_workingtree(tempdir.path(), &ControlDirFormat::default()).unwrap();

        tree.mkdir(std::path::Path::new("debian")).unwrap();

        let mut editor = tree
            .edit_file::<debian_control::Control>(
                &tempdir.path().join("debian/control"),
                false,
                false,
            )
            .unwrap();

        assert!(!editor.has_changed());
        let mut source = editor.add_source("blah");
        source.set_homepage(&"https://example.com".parse().unwrap());
        assert!(editor.has_changed());
        assert_eq!(
            editor.commit().unwrap(),
            vec![&tempdir.path().join("debian/control")]
        );

        assert_eq!(
            "Source: blah\nHomepage: https://example.com/\n",
            std::fs::read_to_string(tempdir.path().join("debian/control")).unwrap()
        );
    }
}
