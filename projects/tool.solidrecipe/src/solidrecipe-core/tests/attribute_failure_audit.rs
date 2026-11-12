//! Attribute audit evidence: failures must remain visible when a kernel caller ignores them.
use solidcore::geom::attribute::{
    Attribute, AttributeHandle, AttributeHandlers, AttributeStore, AttributeView, Behavior,
    ObjectKey, Placement,
};
use solidcore_ops::provenance::with_failure_audit;
use std::sync::{Arc, Barrier};

#[derive(Clone, Debug, PartialEq)]
struct Refused;
impl AttributeHandlers for Refused {
    fn split(
        &self,
        _: &AttributeView<'_>,
        _: ObjectKey,
        _: ObjectKey,
        _: ObjectKey,
    ) -> solidcore::Result<Vec<Placement>> {
        Err(solidcore::SolidError::sm_err(
            "injected attribute handler failure",
        ))
    }
}

#[derive(Clone, Debug, PartialEq)]
struct BadPlacement(AttributeHandle);
impl AttributeHandlers for BadPlacement {
    fn split(
        &self,
        _: &AttributeView<'_>,
        _: ObjectKey,
        _: ObjectKey,
        _: ObjectKey,
    ) -> solidcore::Result<Vec<Placement>> {
        Ok(vec![Placement::Reference {
            on: ObjectKey(2),
            handle: self.0,
        }])
    }
}

fn ignored_handler_failure() {
    let mut store = AttributeStore::default();
    let handle = store
        .insert(Attribute::application(5000, Behavior::Copy, Refused))
        .unwrap();
    store.add_attribute(ObjectKey(1), handle).unwrap();
    // Simulate an upstream caller ignoring the failed notification status.
    assert!(store
        .split(handle, ObjectKey(1), ObjectKey(2), ObjectKey(3))
        .is_err());
}

#[test]
fn reports_handler_and_placement_errors_even_when_caller_ignores_them() {
    let (_, failed) = with_failure_audit(ignored_handler_failure).unwrap();
    assert!(failed);
    let (_, failed) = with_failure_audit(|| {
        let mut store = AttributeStore::default();
        let stale = store
            .insert(Attribute::long(5001, 1, Behavior::Copy))
            .unwrap();
        store.destroy(stale).unwrap();
        let handle = store
            .insert(Attribute::application(
                5002,
                Behavior::Copy,
                BadPlacement(stale),
            ))
            .unwrap();
        store.add_attribute(ObjectKey(1), handle).unwrap();
        assert!(store
            .split(handle, ObjectKey(1), ObjectKey(2), ObjectKey(3))
            .is_err());
    })
    .unwrap();
    assert!(failed);
}

#[test]
fn audit_is_thread_local_and_resets_after_return_nesting_and_panic() {
    let barrier = Arc::new(Barrier::new(2));
    let workers: Vec<_> = [true, false]
        .into_iter()
        .map(|inject| {
            let barrier = Arc::clone(&barrier);
            std::thread::spawn(move || {
                let (_, failed) = with_failure_audit(|| {
                    barrier.wait();
                    if inject {
                        ignored_handler_failure();
                    }
                })
                .unwrap();
                assert_eq!(failed, inject);
                assert!(!with_failure_audit(|| ()).unwrap().1);
            })
        })
        .collect();
    for worker in workers {
        worker.join().unwrap();
    }
    let (_, failed) = with_failure_audit(|| assert!(with_failure_audit(|| ()).is_err())).unwrap();
    assert!(failed, "a refused nested audit invalidates the outer audit");
    assert!(std::panic::catch_unwind(|| with_failure_audit(|| panic!("test panic"))).is_err());
    assert!(!with_failure_audit(|| ()).unwrap().1);
}
