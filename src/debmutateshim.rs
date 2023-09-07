use debversion::Version;
use pyo3::exceptions::PyValueError;
use pyo3::prelude::*;
use pyo3::types::{PyDict, PyTuple};
use std::path::Path;
use std::str::FromStr;

pub struct Deb822Paragraph(pub(crate) PyObject);

impl Deb822Paragraph {
    pub fn insert(&self, key: &str, value: &str) {
        Python::with_gil(|py| {
            self.0.call_method1(py, "insert", (key, value)).unwrap();
        })
    }

    pub fn remove(&self, key: &str) {
        Python::with_gil(|py| {
            self.0.call_method1(py, "remove", (key,)).unwrap();
        })
    }

    pub fn get(&self, key: &str) -> Option<String> {
        Python::with_gil(|py| {
            let result = self.0.call_method1(py, "get", (key,)).unwrap();
            if result.is_none(py) {
                None
            } else {
                Some(result.extract(py).unwrap())
            }
        })
    }
}

pub struct ControlEditor(pub(crate) PyObject);

impl ControlEditor {
    pub fn open(path: Option<&Path>) -> Self {
        Python::with_gil(|py| {
            let path = path.map_or_else(|| "debian/control", |p| p.to_str().unwrap());
            let control = py
                .import("debmutate.control")
                .unwrap()
                .call_method1("ControlEditor", (path,))
                .unwrap();
            let o = control.to_object(py);
            o.call_method0(py, "__enter__").unwrap();
            ControlEditor(o)
        })
    }

    pub fn create(path: Option<&Path>) -> Self {
        Python::with_gil(|py| {
            let path = path.map_or_else(|| "debian/control", |p| p.to_str().unwrap());
            let control = py
                .import("debmutate.control")
                .unwrap()
                .getattr("ControlEditor")
                .unwrap()
                .call_method1("create", (path,))
                .unwrap();
            let o = control.to_object(py);
            o.call_method0(py, "__enter__").unwrap();
            ControlEditor(o)
        })
    }

    pub fn source(&self) -> Option<Deb822Paragraph> {
        Python::with_gil(|py| {
            let result = self.0.getattr(py, "source").unwrap();
            if result.is_none(py) {
                None
            } else {
                Some(Deb822Paragraph(result))
            }
        })
    }

    pub fn binaries(&self) -> Vec<Deb822Paragraph> {
        Python::with_gil(|py| {
            let elements = self.0.getattr(py, "binaries").unwrap();
            let mut binaries = vec![];
            for elem in elements.as_ref(py).iter().unwrap() {
                let elem = elem.unwrap();
                binaries.push(Deb822Paragraph(elem.to_object(py)));
            }
            binaries
        })
    }
}

impl Drop for ControlEditor {
    fn drop(&mut self) {
        Python::with_gil(|py| {
            self.0
                .call_method1(py, "__exit__", (py.None(), py.None(), py.None()))
                .unwrap();
        })
    }
}

#[derive(Debug, PartialEq, Eq)]
pub struct ArchRestriction {
    pub enabled: bool,
    pub arch: String,
}

impl FromPyObject<'_> for ArchRestriction {
    fn extract(ob: &PyAny) -> PyResult<Self> {
        let enabled = ob.getattr("enabled")?.extract()?;
        let arch = ob.getattr("arch")?.extract()?;
        Ok(ArchRestriction { enabled, arch })
    }
}

impl ToPyObject for ArchRestriction {
    fn to_object(&self, py: Python) -> PyObject {
        let enabled = self.enabled.to_object(py);
        let arch = self.arch.to_object(py);
        let ar_cls = py
            .import("debmutate.control")
            .unwrap()
            .getattr("PkgRelation")
            .unwrap()
            .getattr("ArchRestriction")
            .unwrap();
        ar_cls.call1((enabled, arch)).unwrap().to_object(py)
    }
}

#[derive(Debug, PartialEq, Eq)]
pub struct BuildRestriction {
    pub enabled: bool,
    pub profile: String,
}

impl FromPyObject<'_> for BuildRestriction {
    fn extract(ob: &PyAny) -> PyResult<Self> {
        let enabled = ob.getattr("enabled")?.extract()?;
        let profile = ob.getattr("profile")?.extract()?;
        Ok(BuildRestriction { enabled, profile })
    }
}

impl ToPyObject for BuildRestriction {
    fn to_object(&self, py: Python) -> PyObject {
        let enabled = self.enabled.to_object(py);
        let profile = self.profile.to_object(py);
        let br_cls = py
            .import("debmutate.control")
            .unwrap()
            .getattr("PkgRelation")
            .unwrap()
            .getattr("BuildRestriction")
            .unwrap();
        br_cls.call1((enabled, profile)).unwrap().to_object(py)
    }
}

#[derive(Debug, PartialEq, Eq)]
pub struct VersionConstraint {
    pub operator: String,
    pub version: Version,
}

impl VersionConstraint {
    pub fn check(&self, version: &Version) -> bool {
        match self.operator.as_str() {
            "=" => version == &self.version,
            "<<" => version < &self.version,
            "<=" => version <= &self.version,
            ">>" => version > &self.version,
            ">=" => version >= &self.version,
            _ => panic!("Unknown operator {}", self.operator),
        }
    }
}

impl FromPyObject<'_> for VersionConstraint {
    fn extract(ob: &PyAny) -> PyResult<Self> {
        // Extract operator and version from ob (a tuple)
        if ob.len()? != 2 {
            return Err(PyValueError::new_err(
                "VersionConstraint must be a tuple of length 2",
            ));
        }
        let operator = ob.get_item(0)?.extract()?;
        let version = ob.get_item(1)?;
        if let Ok(version) = Version::extract(version) {
            Ok(VersionConstraint { operator, version })
        } else {
            Ok(VersionConstraint {
                operator,
                version: version.extract::<String>()?.parse().unwrap(),
            })
        }
    }
}

impl ToPyObject for VersionConstraint {
    fn to_object(&self, py: Python) -> PyObject {
        let operator = self.operator.to_object(py);
        let version = self.version.to_object(py);
        PyTuple::new(py, vec![operator, version]).to_object(py)
    }
}

#[derive(Debug, PartialEq, Eq)]
pub struct ParsedRelation {
    pub name: String,
    pub archqual: Option<String>,
    pub version: Option<VersionConstraint>,
    pub arch: Option<Vec<ArchRestriction>>,
    pub restrictions: Option<Vec<BuildRestriction>>,
}

pub struct PkgRelation(Vec<Vec<ParsedRelation>>);

impl FromPyObject<'_> for ParsedRelation {
    fn extract(ob: &PyAny) -> PyResult<Self> {
        let name = ob.getattr("name")?.extract()?;
        let archqual = ob.getattr("archqual")?.extract()?;
        let version = ob.getattr("version")?.extract()?;
        let arch = ob.getattr("arch")?.extract()?;
        let restrictions = ob.getattr("restrictions")?.extract()?;
        Ok(ParsedRelation {
            name,
            archqual,
            version,
            arch,
            restrictions,
        })
    }
}

impl ToPyObject for ParsedRelation {
    fn to_object(&self, py: Python) -> PyObject {
        let pr_cls = py
            .import("debmutate._deb822")
            .unwrap()
            .getattr("PkgRelation")
            .unwrap();
        let ret = PyDict::new(py);
        ret.set_item("name", self.name.to_object(py)).unwrap();
        ret.set_item("archqual", self.archqual.to_object(py))
            .unwrap();
        ret.set_item("version", self.version.to_object(py)).unwrap();
        ret.set_item("arch", self.arch.to_object(py)).unwrap();
        ret.set_item("restrictions", self.restrictions.to_object(py))
            .unwrap();
        pr_cls.call((), Some(ret)).unwrap().to_object(py)
    }
}

pub fn format_relations(relations: &[(&str, &[ParsedRelation], &str)]) -> String {
    Python::with_gil(|py| {
        let relations = relations.to_object(py);
        println!("relations: {}", relations);
        let result = py
            .import("debmutate.control")
            .unwrap()
            .call_method1("format_relations", (relations,));
        result.unwrap().extract().unwrap()
    })
}

pub fn parse_relations(relations: &str) -> Vec<(String, Vec<ParsedRelation>, String)> {
    Python::with_gil(|py| {
        let result = py
            .import("debmutate.control")
            .unwrap()
            .call_method1("parse_relations", (relations,))
            .unwrap();
        result.extract().unwrap()
    })
}

#[cfg(test)]
mod tests {
    #[test]
    fn test_create() {
        use super::ControlEditor;
        let td = tempfile::tempdir().unwrap();
        let ce = ControlEditor::create(Some(td.path().join("control").as_path()));
        assert!(ce.source().is_some());
        assert!(ce.binaries().is_empty());
    }

    #[test]
    fn parse_relations() {
        assert_eq!(
            super::parse_relations("foo (>= 1.0) [amd64]"),
            vec![(
                "".to_string(),
                vec![super::ParsedRelation {
                    name: "foo".to_string(),
                    archqual: None,
                    version: Some(super::VersionConstraint {
                        operator: ">=".to_string(),
                        version: "1.0".parse().unwrap()
                    }),
                    arch: Some(vec![super::ArchRestriction {
                        enabled: true,
                        arch: "amd64".to_string()
                    }]),
                    restrictions: None
                }],
                "".to_string()
            )]
        );
    }

    #[test]
    fn format_relations() {
        assert_eq!(
            super::format_relations(&[(
                "",
                &[super::ParsedRelation {
                    name: "foo".to_string(),
                    archqual: None,
                    version: Some(super::VersionConstraint {
                        operator: ">=".to_string(),
                        version: "1.0".parse().unwrap()
                    }),
                    arch: Some(vec![super::ArchRestriction {
                        enabled: true,
                        arch: "amd64".to_string()
                    }]),
                    restrictions: None
                }],
                ""
            )]),
            "foo (>= 1.0) [amd64]"
        );
    }
}