//! Operation-local provenance carried on the same SolidCore bodies used for geometry.
//!
//! Tags name operand record indices only for one operation. The evaluator composes
//! them into persistent identities; they must never escape as persistent names.
use crate::{Body, Result};
use solidcore_ops::provenance::{self, Provenance, FIRST_ID};
use solidcore_ops::{
    blend_ordered, boolean::boolean as kernel_boolean, Blend, BooleanOp, Corners, Order,
};
use std::collections::BTreeSet;

#[derive(Clone, Debug, PartialEq)]
struct Origins(BTreeSet<(usize, usize)>);
impl Origins {
    fn join(&self, other: Option<&Self>) -> Option<Self> {
        let mut origins = self.0.clone();
        if let Some(other) = other {
            origins.extend(&other.0);
        }
        Some(Self(origins))
    }
}
impl Provenance for Origins {
    const ID: u64 = FIRST_ID + 81;
    fn split(&self, other: Option<&Self>) -> Option<Self> {
        self.join(other)
    }
    fn merge(&self, other: Option<&Self>) -> Option<Self> {
        self.join(other)
    }
    fn coincident(&self, other: Option<&Self>) -> Option<Self> {
        self.join(other)
    }
}

pub(crate) struct History {
    pub record: solidcore_record::brep::Brep,
    pub order: Order,
    pub faces: Vec<Vec<(usize, usize)>>,
    pub edges: Vec<Vec<(usize, usize)>>,
}

/// Replace any prior operation tags; identities are carried by the evaluator's
/// input reports, not by stale tags inherited through a copy or earlier operation.
fn tag(
    body: &Body,
    record: &solidcore_record::brep::Brep,
    order: &Order,
    operand: usize,
) -> solidcore_ops::Result<()> {
    let faces: Vec<_> = (0..record.faces.len())
        .map(|index| Origins(BTreeSet::from([(operand, index)])))
        .collect();
    let edges: Vec<_> = (0..record.edges.len())
        .map(|index| Origins(BTreeSet::from([(operand, index)])))
        .collect();
    provenance::write_provenance(body, record, order, &faces, &edges)?;
    Ok(())
}

/// An untagged output has no established source; it is not safe to infer one
/// from proximity, or to claim that it is necessarily a newly generated entity.
fn history(body: &Body) -> solidcore_ops::Result<History> {
    let (record, order, faces, edges) = provenance::read_provenance::<Origins>(body)?;
    let convert = |tags: Vec<Option<Origins>>| {
        tags.into_iter()
            .map(|tag| tag.map_or_else(Vec::new, |tag| tag.0.into_iter().collect()))
            .collect()
    };
    Ok(History {
        record,
        order,
        faces: convert(faces),
        edges: convert(edges),
    })
}

pub(crate) fn boolean(
    left: Body,
    left_record: &solidcore_record::brep::Brep,
    left_order: &Order,
    right: Body,
    right_record: &solidcore_record::brep::Brep,
    right_order: &Order,
    op: BooleanOp,
) -> Result<(Body, History)> {
    let (result, failed) = provenance::with_failure_audit(|| -> solidcore_ops::Result<_> {
        tag(&left, left_record, left_order, 0)?;
        tag(&right, right_record, right_order, 1)?;
        let Some(body) = kernel_boolean(left, right, op)? else {
            return Ok(None);
        };
        let history = history(&body)?;
        Ok(Some((body, history)))
    })?;
    // An ignored notification error may have discarded a lineage update. No
    // geometry or report from this operation may enter the cache in that case.
    if failed {
        return Err(
            "kernel provenance is incomplete: an attribute callback or audit scope failed".into(),
        );
    }
    result?.ok_or_else(|| "empty result".into())
}

/// The order and selected indices must come from this exact input body, avoiding
/// a second point picker and avoiding any record import or geometric matching.
pub(crate) fn blend(
    body: Body,
    record: &solidcore_record::brep::Brep,
    order: &Order,
    selected: &[usize],
    kind: &str,
    size: f64,
) -> Result<(Body, History)> {
    let (result, failed) = provenance::with_failure_audit(|| -> solidcore_ops::Result<_> {
        tag(&body, record, order, 0)?;
        let blend = if kind == "fillet" {
            Blend::Round
        } else {
            Blend::Chamfer
        };
        blend_ordered(
            &body,
            order,
            blend,
            selected,
            &[size],
            &[],
            Corners::Filled,
            Default::default(),
        )?;
        let history = history(&body)?;
        Ok((body, history))
    })?;
    if failed {
        return Err(
            "kernel provenance is incomplete: an attribute callback or audit scope failed".into(),
        );
    }
    Ok(result?)
}
