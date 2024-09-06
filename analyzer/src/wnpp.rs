use sqlx::encode::IsNull;
use sqlx::error::BoxDynError;
use sqlx::{Error, FromRow, PgPool, Postgres, Row, ValueRef};

type BugId = i64;

#[derive(Debug, PartialEq, Eq, PartialOrd, Ord)]
pub enum BugKind {
    RFP,
    ITP,
}

impl std::str::FromStr for BugKind {
    type Err = String;

    fn from_str(s: &str) -> Result<Self, Self::Err> {
        match s {
            "RFP" => Ok(BugKind::RFP),
            "ITP" => Ok(BugKind::ITP),
            _ => Err(format!("Unknown bug kind: {}", s)),
        }
    }
}

impl std::fmt::Display for BugKind {
    fn fmt(&self, f: &mut std::fmt::Formatter) -> std::fmt::Result {
        match self {
            BugKind::RFP => write!(f, "RFP"),
            BugKind::ITP => write!(f, "ITP"),
        }
    }
}

impl sqlx::Type<Postgres> for BugKind {
    fn type_info() -> <Postgres as sqlx::Database>::TypeInfo {
        <String as sqlx::Type<Postgres>>::type_info()
    }
}

impl sqlx::Decode<'_, Postgres> for BugKind {
    fn decode(value: <Postgres as sqlx::Database>::ValueRef<'_>) -> Result<Self, BoxDynError> {
        let s = <String as sqlx::Decode<Postgres>>::decode(value)?;
        s.parse().map_err(Into::into)
    }
}

#[cfg(feature = "pyo3")]
impl pyo3::FromPyObject<'_> for BugKind {
    fn extract_bound(ob: &pyo3::Bound<pyo3::PyAny>) -> pyo3::PyResult<Self> {
        use pyo3::prelude::*;
        let s: String = ob.extract()?;
        s.parse().map_err(pyo3::exceptions::PyValueError::new_err)
    }
}

/// Read DebBugs data through UDD.
pub struct DebBugs {
    pool: PgPool,
}

impl DebBugs {
    pub fn new(pool: PgPool) -> Self {
        DebBugs { pool }
    }

    pub async fn default() -> Result<Self, Error> {
        Ok(DebBugs {
            pool: crate::udd::connect_udd_mirror().await?,
        })
    }

    /// Check that a bug belongs to a particular package.
    ///
    /// # Arguments
    /// * `package` - Package name
    /// * `bugid` - Bug number
    pub async fn check_bug(&self, package: &str, bugid: BugId) -> Result<bool, Error> {
        let actual_package: Option<String> =
            sqlx::query_scalar("select package from bugs where id = $1")
                .bind(bugid)
                .fetch_optional(&self.pool)
                .await?;

        Ok(actual_package.as_deref() == Some(package))
    }

    pub async fn find_archived_wnpp_bugs(
        &self,
        source_name: &str,
    ) -> Result<Vec<(BugId, BugKind)>, Error> {
        sqlx::query_as::<_, (BugId, BugKind)>(
            "select id, substring(title, 0, 3) from archived_bugs where package = 'wnpp' and
            title like 'ITP: ' || $1 || ' -- %' OR
            title like 'RFP: ' || $1 || ' -- %'",
        )
        .bind(source_name)
        .fetch_all(&self.pool)
        .await
    }

    pub async fn find_wnpp_bugs(&self, source_name: &str) -> Result<Vec<(BugId, BugKind)>, Error> {
        sqlx::query_as::<_, (BugId, BugKind)>(
            "select id, type from wnpp where source = $1 and type in ('ITP', 'RFP')",
        )
        .bind(source_name)
        .fetch_all(&self.pool)
        .await
    }
}

pub async fn find_wnpp_bugs_harder(
    source_name: &str,
    upstream_name: &str,
) -> Result<Vec<(BugId, BugKind)>, Error> {
    let debbugs = DebBugs::default().await?;
    let mut wnpp_bugs = debbugs.find_wnpp_bugs(source_name).await?;
    if wnpp_bugs.is_empty() && source_name != upstream_name {
        wnpp_bugs = debbugs.find_wnpp_bugs(upstream_name).await?;
    }
    if wnpp_bugs.is_empty() {
        wnpp_bugs = debbugs.find_archived_wnpp_bugs(source_name).await?;
        if !wnpp_bugs.is_empty() {
            log::warn!(
                "Found archived ITP/RFP bugs for {}: {:?}",
                source_name,
                wnpp_bugs
            );
        } else {
            log::warn!("No relevant WNPP bugs found for {}", source_name);
        }
    } else {
        log::info!("Found WNPP bugs for {}: {:?}", source_name, wnpp_bugs);
    }
    Ok(wnpp_bugs)
}