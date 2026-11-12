//! Exercise the pinned stitch patch through the kernel actually used by SolidRecipe.
use solidcore::curve::curve::Curve;
use solidcore::geom::attribute::{
    Attribute, AttributeHandlers, AttributeView, Behavior, ObjectKey, Placement,
};
use solidcore::math::Point3;
use solidcore::primitive::api_curves::create_line_segment;
use solidcore::topology::brep::{p1, p3, p5, p8};
use solidcore::topology::topology_traverser::Marks;
use solidcore::{Brep, EntityRef, Kernel, SolidError};
use std::sync::{
    atomic::{AtomicUsize, Ordering},
    Arc,
};
#[derive(Clone, Debug)]
struct Notify {
    fail: bool,
    seen: Arc<AtomicUsize>,
}
impl PartialEq for Notify {
    fn eq(&self, other: &Self) -> bool {
        self.fail == other.fail && Arc::ptr_eq(&self.seen, &other.seen)
    }
}
impl AttributeHandlers for Notify {
    fn edit(&self, _: &AttributeView<'_>, _: ObjectKey) -> solidcore::Result<Vec<Placement>> {
        self.seen.fetch_add(1, Ordering::SeqCst);
        if self.fail {
            return Err(SolidError::invalid_input(
                "probe",
                "injected face notification failure",
            ));
        }
        Ok(Vec::new())
    }
}
fn add_face(k: &mut Kernel, b: &mut Brep, corners: &[Point3]) {
    let curves: Vec<Curve> = (0..corners.len())
        .map(|i| {
            Curve::from(create_line_segment(corners[i], corners[(i + 1) % corners.len()]).unwrap())
        })
        .collect();
    p3::with_kernel_callbacks(k, b, |k, b, env| {
        let key_of = env.key_of;
        let this_face = |f| key_of(EntityRef::Face(f));
        let mut marks = Marks::default();
        let region = b.infinite_region();
        p8::create_planar_faces_with_3d_curves(
            k,
            b,
            region,
            &curves,
            0.01,
            &mut p8::FaceBuildEnv {
                env,
                marks: &mut marks,
                this_face: &this_face,
            },
        )
        .map(|_| ())
    })
    .unwrap();
}
fn fixture(k: &mut Kernel, fail: bool, seen: Arc<AtomicUsize>) -> Brep {
    let p = |x, y, z| Point3::new(x, y, z);
    let mut b = p3::new_brep(
        k,
        solidcore::geom::tol::USE_DEFAULT,
        solidcore::geom::tol::USE_DEFAULT,
    )
    .unwrap();
    add_face(
        k,
        &mut b,
        &[p(0., 0., 0.), p(1., 0., 0.), p(1., 0., 1.), p(0., 0., 1.)],
    );
    add_face(
        k,
        &mut b,
        &[p(0., 0., 0.), p(0., 0., 1.), p(-1., 0., 1.), p(-1., 0., 0.)],
    );
    // This face is not incident to the glued edge. Only the post-stitch
    // all-faces notification can reach its marker.
    add_face(
        k,
        &mut b,
        &[
            p(10., 0., 0.),
            p(11., 0., 0.),
            p(11., 0., 1.),
            p(10., 0., 1.),
        ],
    );
    let last = *p1::faces(&b, None).unwrap().last().unwrap();
    b.add_attribute(
        EntityRef::Face(last),
        Attribute::application(19001, Behavior::Copy, Notify { fail, seen }),
    )
    .unwrap();
    b
}
#[test]
fn stitched_face_preedit_reaches_real_attributes() {
    let seen = Arc::new(AtomicUsize::new(0));
    let mut k = Kernel::default();
    let mut b = fixture(&mut k, false, seen.clone());
    p5::stitch_and_orient(
        &mut k,
        &mut b,
        &p5::StitchAndOrientOptions {
            allow_spine_edges: true,
            ..Default::default()
        },
    )
    .unwrap();
    assert!(
        seen.load(Ordering::SeqCst) > 0,
        "detached face must receive all-faces PreEdit after the other pair stitches"
    );
}
#[test]
fn strict_mode_propagates_ordinary_notification_failure() {
    let mut k = Kernel::default();
    k.fixes.brep_edit_statuses_pass_on = true;
    let mut b = fixture(&mut k, true, Arc::new(AtomicUsize::new(0)));
    let err = p5::stitch_and_orient(
        &mut k,
        &mut b,
        &p5::StitchAndOrientOptions {
            allow_spine_edges: true,
            ..Default::default()
        },
    )
    .unwrap_err();
    assert!(err
        .to_string()
        .contains("injected face notification failure"));
}
#[test]
fn legacy_mode_still_ignores_ordinary_notification_failure() {
    let mut k = Kernel::default();
    let mut b = fixture(&mut k, true, Arc::new(AtomicUsize::new(0)));
    assert!(p5::stitch_and_orient(
        &mut k,
        &mut b,
        &p5::StitchAndOrientOptions {
            allow_spine_edges: true,
            ..Default::default()
        }
    )
    .is_ok());
}
#[test]
fn strict_error_rolls_back_body_through_transaction() {
    let mut k = Kernel::default();
    k.fixes.brep_edit_statuses_pass_on = true;
    let mut b = fixture(&mut k, true, Arc::new(AtomicUsize::new(0)));
    let marked_face = *p1::faces(&b, None).unwrap().last().unwrap();
    let before = solidcore_convert::brep::to_record(&mut k, &mut b)
        .unwrap()
        .0;
    let result = b.with_rollback(
        |body| {
            p5::stitch_and_orient(
                &mut k,
                body,
                &p5::StitchAndOrientOptions {
                    allow_spine_edges: true,
                    ..Default::default()
                },
            )
        },
        |result| result.is_ok(),
    );
    assert!(result.is_err());
    assert_eq!(
        solidcore_convert::brep::to_record(&mut k, &mut b)
            .unwrap()
            .0,
        before
    );
    assert!(
        b.entity_attributes(EntityRef::Face(marked_face))
            .iter()
            .any(|(_, attribute)| attribute.application_value::<Notify>().is_some()),
        "rollback must restore the face's notification attribute"
    );
}
