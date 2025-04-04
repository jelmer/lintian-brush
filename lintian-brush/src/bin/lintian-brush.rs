use breezyshim::branch::open_containing as open_containing_branch;
use breezyshim::error::Error;
use breezyshim::tree::MutableTree;
use breezyshim::workingtree;
use clap::Parser;
use debian_changelog::get_maintainer;
use distro_info::DistroInfo;

use debian_analyzer::{get_committer, Certainty};
use lintian_brush::{ManyResult, OverallError};
use std::collections::HashMap;
use std::io::Write as _;
use std::path::PathBuf;

#[derive(clap::Args, Clone, Debug)]
#[group()]
struct FixerArgs {
    /// Specific fixers to run
    fixers: Option<Vec<String>>,

    /// Path to fixer scripts
    #[arg(short, long)]
    fixers_dir: Option<PathBuf>,

    /// Exclude fixers
    #[arg(long, value_name = "EXCLUDE", help_heading = Some("Fixers"))]
    exclude: Option<Vec<String>>,

    /// Use features/compatibility levels that are not available in stable. (makes backporting
    /// harder)
    #[arg(long, conflicts_with = "compat_release")]
    modern: bool,

    #[arg(
        long,
        env = "COMPAT_RELEASE",
        value_name = "RELEASE",
        hide = true,
        conflicts_with = "modern"
    )]
    compat_release: Option<String>,

    #[arg(long, hide = true)]
    minimum_certainty: Option<Certainty>,

    #[arg(long, hide = true, default_value_t = true)]
    opinionated: bool,

    #[arg(long, hide = true, default_value_t = 0, value_name = "DILIGENCE")]
    diligent: i32,

    /// Include changes with lower certainty
    #[arg(long, default_value_t = false)]
    uncertain: bool,

    #[arg(long, default_value_t = false, hide = true)]
    yolo: bool,

    #[arg(long, default_value_t = false, hide = true)]
    force_subprocess: bool,
}

#[derive(clap::Args, Clone, Debug)]
#[group()]
struct PackageArgs {
    /// Allow file reformatting and stripping of comments
    #[arg(short, long)]
    allow_reformatting: Option<bool>,

    /// Whether to trust the package
    #[arg(long, default_value_t = false, hide = true)]
    trust: bool,
}

#[derive(clap::Args, Clone, Debug)]
#[group()]
struct OutputArgs {
    /// Be verbose
    #[arg(short, long, default_value_t = std::env::var("SVP_API").is_ok())]
    verbose: bool,

    /// Print resulting diff afterwards
    #[arg(long, default_value_t = false)]
    diff: bool,

    /// Enable debug output
    #[arg(long, default_value_t = false)]
    debug: bool,

    /// List available fixers
    #[arg(
        long,
        default_value_t = false,
        conflicts_with = "list_tags",
        conflicts_with = "identity"
    )]
    list_fixers: bool,

    /// List lintian tags for which fixers are available
    #[arg(
        long,
        default_value_t = false,
        conflicts_with = "list_fixers",
        conflicts_with = "identity"
    )]
    list_tags: bool,

    /// Do not make any changes to the current repository.
    /// Note: currently creates a temporary clone of the repository.
    #[arg(long, default_value_t = false)]
    dry_run: bool,

    /// Print user identity that would be used when committing
    #[arg(
        long,
        default_value_t = false,
        conflicts_with = "list_fixers",
        conflicts_with = "list_tags"
    )]
    identity: bool,

    /// directory to run in
    #[arg(short, long, default_value = std::env::current_dir().unwrap().into_os_string(), value_name = "DIR")]
    directory: std::path::PathBuf,

    /// Do not probe external services
    #[arg(long, default_value_t = false)]
    disable_net_access: bool,

    /// Disable inotify
    #[arg(long, default_value_t = false, hide = true)]
    disable_inotify: bool,

    /// Document changes in the changelog [default: auto-detect]
    #[arg(long, default_value_t = false, conflicts_with = "no_update_changelog")]
    update_changelog: bool,

    /// Do not document changes in the changelog (useful when using e.g. "gbp dch") [default: auto-detect]
    #[arg(long, default_value_t = false, conflicts_with = "update_changelog")]
    no_update_changelog: bool,
}

#[derive(Parser, Debug)]
#[command(author, version)]
struct Args {
    #[command(flatten)]
    fixers: FixerArgs,

    #[command(flatten)]
    packages: PackageArgs,

    #[command(flatten)]
    output: OutputArgs,
}

fn main() -> Result<(), i32> {
    let args = Args::parse();

    env_logger::builder()
        .format(|buf, record| writeln!(buf, "{}", record.args()))
        .filter(
            None,
            if args.output.debug {
                log::LevelFilter::Debug
            } else {
                log::LevelFilter::Info
            },
        )
        .init();

    breezyshim::init();

    // TODO(jelmer): Allow changing this via arguments
    let timeout = Some(chrono::Duration::seconds(10));

    let fixers_iter = match lintian_brush::available_lintian_fixers(
        args.fixers.fixers_dir.as_deref(),
        Some(args.fixers.force_subprocess),
    ) {
        Ok(fixers) => fixers,
        Err(e) => {
            log::error!("Error loading fixers: {}", e);
            std::process::exit(1);
        }
    };

    let mut fixers: Vec<_> = fixers_iter.collect();

    if args.output.list_fixers {
        fixers.sort_by_key(|a| a.name());
        for fixer in fixers {
            println!("{}", fixer.name());
        }
    } else if args.output.list_tags {
        let tags = fixers
            .iter()
            .flat_map(|f| f.lintian_tags())
            .collect::<std::collections::HashSet<_>>();
        let mut tags: Vec<_> = tags.into_iter().collect();
        tags.sort();
        for tag in tags {
            println!("{}", tag);
        }
    } else {
        let mut update_changelog: Option<bool> = if args.output.update_changelog {
            Some(true)
        } else if args.output.no_update_changelog {
            Some(false)
        } else {
            None
        };

        let mut tempdir = None;

        let (wt, subpath) = if args.output.dry_run {
            let (branch, subpath) = match open_containing_branch(
                &url::Url::from_directory_path(&args.output.directory).unwrap(),
            ) {
                Ok((branch, subpath)) => (branch, subpath),
                Err(Error::NotBranchError(_msg, _)) => {
                    log::error!("No version control directory found (e.g. a .git directory).");
                    std::process::exit(1);
                }
                Err(Error::DependencyNotPresent(name, _reason)) => {
                    log::error!(
                        "Unable to open branch at {}: missing package {}",
                        args.output.directory.display(),
                        name
                    );
                    std::process::exit(1);
                }
                Err(err) => {
                    log::error!(
                        "Unable to open branch at {}: {}",
                        args.output.directory.display(),
                        err
                    );
                    std::process::exit(1);
                }
            };

            let td = match tempfile::tempdir() {
                Ok(td) => td,
                Err(e) => {
                    log::error!("Unable to create temporary directory: {}", e);
                    std::process::exit(1);
                }
            };

            // TODO(jelmer): Make a slimmer copy

            let to_dir = match branch.controldir().sprout(
                url::Url::from_directory_path(td.path()).unwrap(),
                Some(branch.as_ref()),
                Some(true),
                Some(branch.format().supports_stacking()),
                None,
            ) {
                Ok(to_dir) => to_dir,
                Err(e) => {
                    log::error!("Unable to create temporary branch: {}", e);
                    std::process::exit(1);
                }
            };
            tempdir = Some(td);
            (to_dir.open_workingtree().unwrap(), subpath)
        } else {
            match workingtree::open_containing(&args.output.directory) {
                Ok((wt, subpath)) => (wt, subpath.display().to_string()),
                Err(Error::NotBranchError(_msg, _)) => {
                    log::error!("No version control directory found (e.g. a .git directory).");
                    std::process::exit(1);
                }
                Err(Error::DependencyNotPresent(name, _reason)) => {
                    log::error!(
                        "Unable to open tree at {}: missing package {}",
                        args.output.directory.display(),
                        name
                    );
                    std::process::exit(1);
                }
                Err(e) => {
                    log::error!(
                        "Unable to open tree at {}: {}",
                        args.output.directory.display(),
                        e
                    );
                    std::process::exit(1);
                }
            }
        };
        if args.output.identity {
            println!("Committer identity: {}", get_committer(&wt));
            let (maintainer, email) = get_maintainer().unwrap_or(("".to_string(), "".to_string()));
            println!("Changelog identity: {} <{}>", maintainer, email);
            std::process::exit(0);
        }

        let svp = svp_client::Reporter::new(versions_dict());

        let since_revid = wt.last_revision().unwrap();
        if args.fixers.fixers.is_some() || args.fixers.exclude.is_some() {
            let include = args
                .fixers
                .fixers
                .as_ref()
                .map(|fs| fs.iter().map(|f| f.as_str()).collect::<Vec<_>>());
            let exclude = args
                .fixers
                .exclude
                .as_ref()
                .map(|fs| fs.iter().map(|f| f.as_str()).collect::<Vec<_>>());
            fixers =
                match lintian_brush::select_fixers(fixers, include.as_deref(), exclude.as_deref()) {
                    Ok(fixers) => fixers,
                    Err(lintian_brush::UnknownFixer(f)) => {
                        log::error!("Unknown fixer specified: {}", f);
                        std::process::exit(1);
                    }
                }
        }
        let debian_info = distro_info::DebianDistroInfo::new().unwrap();
        let mut compat_release = if args.fixers.modern {
            Some(
                debian_info
                    .releases()
                    .iter()
                    .find(|release| release.series() == "sid")
                    .unwrap()
                    .series()
                    .to_string(),
            )
        } else {
            args.fixers.compat_release.clone()
        };
        let mut minimum_certainty = args.fixers.minimum_certainty;
        let mut allow_reformatting = args.packages.allow_reformatting;
        match debian_analyzer::config::Config::from_workingtree(
            &wt,
            std::path::Path::new(subpath.as_str()),
        ) {
            Err(e) if e.kind() == std::io::ErrorKind::NotFound => {}
            Err(e) => {
                log::error!("Unable to read config: {}", e);
                std::process::exit(1);
            }
            Ok(cfg) => {
                if minimum_certainty.is_none() {
                    minimum_certainty = cfg.minimum_certainty();
                }
                if compat_release.is_none() {
                    compat_release = cfg.compat_release();
                }
                if allow_reformatting.is_none() {
                    allow_reformatting = cfg.allow_reformatting();
                }
                if update_changelog.is_none() {
                    update_changelog = cfg.update_changelog();
                }
            }
        }
        let minimum_certainty = minimum_certainty.unwrap_or_else(|| {
            if args.fixers.uncertain || args.fixers.yolo {
                Certainty::Possible
            } else {
                Certainty::default()
            }
        });
        let compat_release = compat_release.as_ref().map_or_else(
            || {
                debian_info
                    .released(chrono::Local::now().naive_local().date())
                    .into_iter()
                    .next_back()
                    .unwrap()
                    .series()
                    .to_string()
            },
            |s| s.clone(),
        );

        if args.output.verbose {
            log::info!("Using parameters:");
            log::info!(" compatibility release: {}", compat_release);
            log::info!(" minimum certainty: {}", minimum_certainty);
            if let Some(allow_reformatting) = allow_reformatting {
                log::info!(" allow reformatting: {}", allow_reformatting);
            } else {
                log::info!(" allow reformatting: auto");
            }
            if let Some(update_changelog) = update_changelog {
                log::info!(" update changelog: {}", update_changelog);
            } else {
                log::info!(" update changelog: auto");
            }
        }

        let write_lock = wt.lock_write();
        if debian_analyzer::control_files_in_root(&wt, std::path::Path::new(subpath.as_str())) {
            drop(write_lock);
            svp.report_fatal(
                "control-files-in-root",
                "control files live in root rather than debian/ (LarstIQ mode)",
                None,
                Some(false),
            );
        }

        #[cfg(feature = "python")]
        {
            // Ensure we can find the lintian_brush.fixer python module
            let e = pyo3::Python::with_gil(|py| {
                if let Err(e) = py.import_bound("lintian_brush.fixer") {
                    Some(e)
                } else {
                    None
                }
            });

            if let Some(e) = e {
                drop(write_lock);
                svp.report_fatal(
                    "python-import-error",
                    format!("Error importing lintian_brush.fixer: {}", e).as_str(),
                    Some("Ensure that the lintian-brush Python package is in Python's sys.path."),
                    Some(false),
                );
            }
        }

        let preferences = lintian_brush::FixerPreferences {
            compat_release: Some(compat_release),
            minimum_certainty: Some(minimum_certainty),
            allow_reformatting,
            net_access: Some(!args.output.disable_net_access),
            opinionated: Some(args.fixers.opinionated),
            diligence: Some(args.fixers.diligent),
            trust_package: Some(args.packages.trust),
        };

        let mut overall_result = match lintian_brush::run_lintian_fixers(
            &wt,
            fixers.as_slice(),
            update_changelog.as_ref().map(|b| (|| *b)),
            args.output.verbose,
            None,
            &preferences,
            if args.output.disable_inotify {
                Some(false)
            } else {
                None
            },
            Some(std::path::Path::new(subpath.as_str())),
            Some("lintian-brush"),
            timeout,
        ) {
            Err(OverallError::NotDebianPackage(p)) => {
                drop(write_lock);
                svp.report_fatal(
                    "not-debian-package",
                    format!("{}: Not a Debian package", p.display()).as_str(),
                    None,
                    None,
                );
            }
            Err(OverallError::WorkspaceDirty(p)) => {
                drop(write_lock);
                log::error!(
                    "{}: Please commit pending changes and remove unknown files first.",
                    p.display()
                );
                if args.output.verbose {
                    breezyshim::status::show_tree_status(&wt).unwrap();
                }
                std::process::exit(1);
            }
            Err(OverallError::ChangelogCreate(e)) => {
                drop(write_lock);
                svp.report_fatal(
                    "changelog-create-error",
                    format!("Error creating changelog entry: {}", e).as_str(),
                    None,
                    None,
                );
            }
            Err(OverallError::InvalidChangelog(p, s)) => {
                drop(write_lock);
                svp.report_fatal(
                    "invalid-changelog",
                    format!("{}: Invalid changelog: {}", p.display(), s).as_str(),
                    None,
                    None,
                );
            }
            #[cfg(feature = "python")]
            Err(OverallError::Python(e)) => {
                drop(write_lock);
                svp.report_fatal(
                    "python-error",
                    format!("Error running Python: {}", e).as_str(),
                    None,
                    None,
                );
            }
            Err(OverallError::BrzError(e)) => {
                drop(write_lock);
                svp.report_fatal(
                    "internal-error",
                    format!("Tree manipulation error: {}", e).as_str(),
                    None,
                    None,
                );
            }
            Err(OverallError::IoError(e)) => {
                drop(write_lock);
                svp.report_fatal("io-error", format!("I/O error: {}", e).as_str(), None, None);
            }
            Err(OverallError::Other(e)) => {
                drop(write_lock);
                svp.report_fatal(
                    "other-error",
                    format!("Other error: {}", e).as_str(),
                    None,
                    None,
                );
            }
            Ok(overall_result) => overall_result,
        };
        std::mem::drop(write_lock);
        if let Some(tempdir) = tempdir {
            if let Err(e) = tempdir.close() {
                log::warn!("Error removing temporary directory: {}", e);
            }
        }

        if !overall_result.overridden_lintian_issues.is_empty() {
            if overall_result.overridden_lintian_issues.len() == 1 {
                log::info!(
                    "{} change skipped because of lintian overrides.",
                    overall_result.overridden_lintian_issues.len()
                );
            } else {
                log::info!(
                    "{} changes skipped because of lintian overrides.",
                    overall_result.overridden_lintian_issues.len()
                );
            }
        }
        if !overall_result.success.is_empty() {
            let all_tags = overall_result.tags_count();
            if !all_tags.is_empty() {
                log::info!(
                    "Lintian tags fixed: {:?}",
                    all_tags.keys().collect::<Vec<_>>()
                );
            } else {
                log::info!("Some changes were made, but there are no affected lintian tags.");
            }
            let min_certainty = overall_result.minimum_success_certainty();
            if min_certainty != Certainty::Certain {
                log::info!(
                    "Some changes were made with lower certainty ({}); please double check the changes.",
                    min_certainty
                );
            }
        } else {
            log::info!("No changes made.");
        }
        if !overall_result.failed_fixers.is_empty() && !args.output.verbose {
            log::info!("Some fixer scripts failed to run:");
            for (name, reason) in overall_result.failed_fixers.iter() {
                log::info!("  {}: {}", name, reason);
            }
            log::info!("Run with --verbose for details.");
        }
        if !overall_result.formatting_unpreservable.is_empty() && !args.output.verbose {
            log::info!(
                "Some fixer scripts were unable to preserve formatting: {:?}. Run with --allow-reformatting to reformat {:?}.",
                overall_result.formatting_unpreservable.keys().collect::<Vec<_>>(),
                overall_result.formatting_unpreservable.values().collect::<Vec<_>>()
            );
        }
        if args.output.diff {
            breezyshim::diff::show_diff_trees(
                &wt.branch()
                    .repository()
                    .revision_tree(&since_revid)
                    .unwrap(),
                &wt,
                Box::new(std::io::stdout()),
                None,
                None,
            )
            .unwrap();
        }
        if svp.enabled() {
            if let Some(base) = svp.load_resume::<ManyResult>() {
                overall_result.success.extend(base.success);
            }
            let changelog_behaviour = overall_result.changelog_behaviour.clone();
            svp.report_success_debian(
                Some(overall_result.value()),
                Some(overall_result),
                changelog_behaviour.map(|b| b.into()),
            )
        }
    }
    Ok(())
}

fn versions_dict() -> HashMap<String, String> {
    use pyo3::prelude::*;
    let mut ret = HashMap::new();
    ret.insert(
        "lintian-brush".to_string(),
        env!("CARGO_PKG_VERSION").to_string(),
    );
    let breezy_version = breezyshim::version::version();
    ret.insert("breezy".to_string(), breezy_version.to_string());

    pyo3::Python::with_gil(|py| {
        let debmutate = py.import_bound("debmutate").unwrap();
        ret.insert(
            "debmutate".to_string(),
            debmutate
                .getattr("version_string")
                .unwrap()
                .extract()
                .unwrap(),
        );

        let debian = py.import_bound("debian").unwrap();
        ret.insert(
            "debian".to_string(),
            debian.getattr("__version__").unwrap().extract().unwrap(),
        );
    });
    ret
}
