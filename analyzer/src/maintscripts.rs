//! Maintscript file parsing and generation
use debversion::Version;

#[derive(Debug, PartialEq, Eq)]
/// An error that occurred while parsing a maintscript file
pub enum ParseError {
    /// An unknown maintscript command
    UnknownCommand(String),
    /// A maintscript command is missing an argument
    MissingArgument(String),
    /// An invalid version was encountered
    InvalidVersion(debversion::ParseError),
}

impl std::fmt::Display for ParseError {
    fn fmt(&self, f: &mut std::fmt::Formatter) -> std::fmt::Result {
        match self {
            ParseError::UnknownCommand(command) => {
                write!(f, "Unknown maintscript command: {}", command)
            }
            ParseError::MissingArgument(command) => {
                write!(f, "Missing argument for maintscript command: {}", command)
            }
            ParseError::InvalidVersion(e) => write!(f, "Invalid version: {}", e),
        }
    }
}

impl std::error::Error for ParseError {}

impl From<debversion::ParseError> for ParseError {
    fn from(e: debversion::ParseError) -> Self {
        ParseError::InvalidVersion(e)
    }
}

#[derive(Debug, PartialEq, Eq, Clone)]
/// An entry in a maintscript file
pub enum Entry {
    /// A command that is supported by the maintscript
    Supports(String),
    /// Remove a conffile
    RemoveConffile {
        /// The pathname of the conffile
        conffile: String,
        /// The version of the package that is being upgraded
        prior_version: Option<Version>,
        /// The name of the package that is being upgraded
        package: Option<String>,
    },
    /// Move a conffile
    MoveConffile {
        /// The old pathname of the conffile
        old_conffile: String,
        /// The new pathname of the conffile
        new_conffile: String,
        /// The version of the package that is being upgraded
        prior_version: Option<Version>,
        /// The name of the package that is being upgraded
        package: Option<String>,
    },
    /// Convert a symlink to a directory
    SymlinkToDir {
        /// The pathname of the symlink
        pathname: String,
        /// The old target of the symlink
        old_target: String,
        /// The version of the package that is being upgraded
        prior_version: Option<Version>,
        /// The name of the package that is being upgraded
        package: Option<String>,
    },
    /// Convert a directory to a symlink
    DirToSymlink {
        /// The pathname of the directory
        pathname: String,
        /// The new target of the symlink
        new_target: String,
        /// The version of the package that is being upgraded
        prior_version: Option<Version>,
        /// The name of the package that is being upgraded
        package: Option<String>,
    },
}

impl Entry {
    /// Get the arguments of the entry
    fn args(&self) -> Vec<String> {
        match self {
            Entry::Supports(command) => vec!["supports".to_string(), command.to_string()],
            Entry::RemoveConffile {
                conffile,
                prior_version,
                package,
            } => {
                let mut ret = vec!["rm_conffile".to_string(), conffile.to_string()];
                if let Some(prior_version) = prior_version.as_ref() {
                    ret.push(prior_version.to_string());
                    if let Some(package) = package.as_ref() {
                        ret.push(package.to_string());
                    }
                }
                ret
            }
            Entry::MoveConffile {
                old_conffile,
                new_conffile,
                prior_version,
                package,
            } => {
                let mut ret = vec![
                    "mv_conffile".to_string(),
                    old_conffile.to_string(),
                    new_conffile.to_string(),
                ];
                if let Some(prior_version) = prior_version.as_ref() {
                    ret.push(prior_version.to_string());
                    if let Some(package) = package.as_ref() {
                        ret.push(package.to_string());
                    }
                }
                ret
            }
            Entry::SymlinkToDir {
                pathname,
                old_target,
                prior_version,
                package,
            } => {
                let mut ret = vec![
                    "symlink_to_dir".to_string(),
                    pathname.to_string(),
                    old_target.to_string(),
                ];
                if let Some(prior_version) = prior_version.as_ref() {
                    ret.push(prior_version.to_string());
                    if let Some(package) = package.as_ref() {
                        ret.push(package.to_string());
                    }
                }
                ret
            }
            Entry::DirToSymlink {
                pathname,
                new_target,
                prior_version,
                package,
            } => {
                let mut ret = vec![
                    "dir_to_symlink".to_string(),
                    pathname.to_string(),
                    new_target.to_string(),
                ];
                if let Some(prior_version) = prior_version.as_ref() {
                    ret.push(prior_version.to_string());
                    if let Some(package) = package.as_ref() {
                        ret.push(package.to_string());
                    }
                }
                ret
            }
        }
    }

    /// Get the name of the package that is being upgraded
    pub fn package(&self) -> Option<&String> {
        match self {
            Entry::RemoveConffile { package, .. } => package.as_ref(),
            Entry::MoveConffile { package, .. } => package.as_ref(),
            Entry::SymlinkToDir { package, .. } => package.as_ref(),
            Entry::DirToSymlink { package, .. } => package.as_ref(),
            _ => None,
        }
    }

    /// Get the version of the package that is being upgraded
    pub fn prior_version(&self) -> Option<&Version> {
        match self {
            Entry::RemoveConffile { prior_version, .. } => prior_version.as_ref(),
            Entry::MoveConffile { prior_version, .. } => prior_version.as_ref(),
            Entry::SymlinkToDir { prior_version, .. } => prior_version.as_ref(),
            Entry::DirToSymlink { prior_version, .. } => prior_version.as_ref(),
            _ => None,
        }
    }
}

impl std::fmt::Display for Entry {
    fn fmt(&self, f: &mut std::fmt::Formatter) -> std::fmt::Result {
        write!(f, "{}", self.args().join(" "))
    }
}

impl std::str::FromStr for Entry {
    type Err = ParseError;

    fn from_str(s: &str) -> Result<Self, Self::Err> {
        let args: Vec<&str> = s.split_whitespace().collect();
        match args[0] {
            "supports" => {
                if args.len() != 2 {
                    return Err(ParseError::MissingArgument("supports".to_string()));
                }
                Ok(Entry::Supports(args[1].to_string()))
            }
            "rm_conffile" => {
                if args.len() < 2 {
                    return Err(ParseError::MissingArgument("rm_conffile".to_string()));
                }
                let conffile = args[1].to_string();
                let prior_version = if args.len() > 2 {
                    Some(args[2].parse()?)
                } else {
                    None
                };
                let package = if args.len() > 3 {
                    Some(args[3].to_string())
                } else {
                    None
                };
                Ok(Entry::RemoveConffile {
                    conffile,
                    prior_version,
                    package,
                })
            }
            "mv_conffile" => {
                if args.len() < 3 {
                    return Err(ParseError::MissingArgument("mv_conffile".to_string()));
                }
                let old_conffile = args[1].to_string();
                let new_conffile = args[2].to_string();
                let prior_version = if args.len() > 3 {
                    Some(args[3].parse()?)
                } else {
                    None
                };
                let package = if args.len() > 4 {
                    Some(args[4].to_string())
                } else {
                    None
                };
                Ok(Entry::MoveConffile {
                    old_conffile,
                    new_conffile,
                    prior_version,
                    package,
                })
            }
            "symlink_to_dir" => {
                if args.len() < 3 {
                    return Err(ParseError::MissingArgument("symlink_to_dir".to_string()));
                }
                let pathname = args[1].to_string();
                let old_target = args[2].to_string();
                let prior_version = if args.len() > 3 {
                    Some(args[3].parse()?)
                } else {
                    None
                };
                let package = if args.len() > 4 {
                    Some(args[4].to_string())
                } else {
                    None
                };
                Ok(Entry::SymlinkToDir {
                    pathname,
                    old_target,
                    prior_version,
                    package,
                })
            }
            "dir_to_symlink" => {
                if args.len() < 3 {
                    return Err(ParseError::MissingArgument("dir_to_symlink".to_string()));
                }
                let pathname = args[1].to_string();
                let new_target = args[2].to_string();
                let prior_version = if args.len() > 3 {
                    Some(args[3].parse()?)
                } else {
                    None
                };
                let package = if args.len() > 4 {
                    Some(args[4].to_string())
                } else {
                    None
                };
                Ok(Entry::DirToSymlink {
                    pathname,
                    new_target,
                    prior_version,
                    package,
                })
            }
            n => Err(ParseError::UnknownCommand(n.to_string())),
        }
    }
}

#[derive(Debug, PartialEq, Eq, Clone)]
/// A line in a maintscript file
enum Line {
    /// A comment
    Comment(String),
    /// An entry
    Entry(Entry),
}

impl std::fmt::Display for Line {
    fn fmt(&self, f: &mut std::fmt::Formatter) -> std::fmt::Result {
        match self {
            Line::Comment(comment) => write!(f, "# {}", comment),
            Line::Entry(entry) => write!(f, "{}", entry),
        }
    }
}

#[derive(Debug, PartialEq, Eq, Clone)]
/// A maintscript file
pub struct Maintscript {
    lines: Vec<Line>,
}

impl Default for Maintscript {
    fn default() -> Self {
        Self::new()
    }
}

impl Maintscript {
    /// Create a new maintscript file
    pub fn new() -> Self {
        Maintscript { lines: Vec::new() }
    }

    /// Check if the maintscript file is empty
    pub fn is_empty(&self) -> bool {
        self.lines.is_empty()
    }

    /// Iterate over the entries in the maintscript file
    pub fn entries(&self) -> Vec<&Entry> {
        self.lines
            .iter()
            .filter_map(|l| match l {
                Line::Entry(e) => Some(e),
                _ => None,
            })
            .collect()
    }

    /// Remove an entry from the maintscript file
    pub fn remove(&mut self, index: usize) {
        // Also remove preceding comments
        let mut comments = vec![];
        for (i, line) in self.lines.iter().enumerate() {
            match line {
                Line::Comment(_) => comments.push(i),
                Line::Entry(_) => {
                    if i == index {
                        for i in comments.iter().rev() {
                            self.lines.remove(*i);
                        }
                        self.lines.remove(index - comments.len());
                        return;
                    }
                    comments.clear();
                }
            }
        }
    }
}

impl std::fmt::Display for Maintscript {
    fn fmt(&self, f: &mut std::fmt::Formatter) -> std::fmt::Result {
        write!(
            f,
            "{}",
            self.lines
                .iter()
                .map(|e| e.to_string())
                .collect::<Vec<String>>()
                .join("\n")
        )
    }
}

impl std::str::FromStr for Maintscript {
    type Err = ParseError;

    fn from_str(s: &str) -> Result<Self, Self::Err> {
        let lines = s
            .lines()
            .map(|l| {
                if l.starts_with('#') || l.trim().is_empty() {
                    Ok(Line::Comment(l.to_string()))
                } else {
                    Ok(Line::Entry(Entry::from_str(l)?))
                }
            })
            .collect::<Result<Vec<Line>, Self::Err>>()?;
        Ok(Maintscript { lines })
    }
}

#[cfg(test)]
mod tests {
    #[test]
    fn test_maintscript() {
        let maintscript = "supports preinst
rm_conffile /etc/foo.conf 1.2.3-4
mv_conffile /etc/foo.conf /etc/bar.conf 1.2.3-4
symlink_to_dir /etc/foo /etc/bar 1.2.3-4
dir_to_symlink /etc/foo /etc/bar 1.2.3-4";
        let maintscript = maintscript.parse::<super::Maintscript>().unwrap();
        assert_eq!(
            maintscript.entries(),
            vec![
                &super::Entry::Supports("preinst".to_string()),
                &super::Entry::RemoveConffile {
                    conffile: "/etc/foo.conf".to_string(),
                    prior_version: Some("1.2.3-4".parse().unwrap()),
                    package: None
                },
                &super::Entry::MoveConffile {
                    old_conffile: "/etc/foo.conf".to_string(),
                    new_conffile: "/etc/bar.conf".to_string(),
                    prior_version: Some("1.2.3-4".parse().unwrap()),
                    package: None
                },
                &super::Entry::SymlinkToDir {
                    pathname: "/etc/foo".to_string(),
                    old_target: "/etc/bar".to_string(),
                    prior_version: Some("1.2.3-4".parse().unwrap()),
                    package: None
                },
                &super::Entry::DirToSymlink {
                    pathname: "/etc/foo".to_string(),
                    new_target: "/etc/bar".to_string(),
                    prior_version: Some("1.2.3-4".parse().unwrap()),
                    package: None
                },
            ]
        );
    }
}
