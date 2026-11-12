//! Notifications during removal of a contact slit in a real union.
use solidcore::boolean::api_brep::boolean_union;
use solidcore::geom::context::NotifyCallback;
use solidcore::geom::object::{NotifyOperation, ObjectRef};
use solidcore::math::Point3;
use solidcore::primitive::api_primitives::{create_box, create_cylinder};
use solidcore::topology::brep::p1;
use solidcore::topology::face::p2 as face;
use solidcore::Kernel;
use std::sync::{Arc, Mutex};

#[derive(Debug)]
struct Marker(Arc<Mutex<Vec<u64>>>);
impl NotifyCallback for Marker {
    fn execute(
        &mut self,
        operation: NotifyOperation,
        caller: ObjectRef,
        _: Option<ObjectRef>,
        _: Option<ObjectRef>,
        _: Option<ObjectRef>,
    ) -> solidcore::Result<()> {
        if operation == NotifyOperation::Destruction && caller.type_code == 16005 {
            self.0.lock().unwrap().push(caller.key.0);
        }
        Ok(())
    }
}
#[test]
fn touching_union_notifies_edge_uses_with_merge_keys() {
    let mut k = Kernel::default();
    let cube = create_box(&mut k, Point3::new(0., 0., 0.), 10., 10., 10.).unwrap();
    let post = create_cylinder(&mut k, Point3::new(12.5, 5., 2.), 2.5, 6.).unwrap();
    let seen = Arc::new(Mutex::new(Vec::new()));
    k.context
        .set_user_notify_callback(Some(Box::new(Marker(seen.clone()))));
    let body = boolean_union(&mut k, cube, post).unwrap();
    assert!(p1::faces(&body, None)
        .unwrap()
        .into_iter()
        .all(|f| face::loops(&body, f, false, None).unwrap().len() == 1));
    let observed = seen.lock().unwrap();
    assert_eq!(
        observed.len(),
        4,
        "the real contact slit destroys four edge uses"
    );
    // Merge namespace 0 names primary edge uses as kind 11. Local arena keys
    // use kind 7 and cannot address attributes in the merge's store.
    assert!(
        observed.iter().all(|key| key >> 32 == 11),
        "slit callbacks must use the merge's edge-use keys: {observed:?}"
    );
}
