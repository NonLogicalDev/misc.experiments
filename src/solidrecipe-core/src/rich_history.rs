//! A foundation for retaining operation-local B-rep history without flattening it.
//!
//! This module is not yet connected to SolidRecipe's evaluator or public Python
//! interface. A producer must supply a result record and its actual history as
//! one evaluation; neither a record index nor a graph name is an identity across
//! revisions. In particular, the current evaluator's untagged entities are not
//! enough to populate the richer history supplied here.
//!
//! Histories are kept as a DAG because an operation may create an edge at a
//! meeting of faces and the next operation may generate a fillet from that edge.
//! Flattening the two histories into one is not supported by the kernel's
//! `History::substitute` representation. Walking stage by stage preserves both
//! operations and never replaces missing evidence with a geometric guess.

use solidcore_record::brep::{history, Brep};
use std::collections::{BTreeMap, BTreeSet};
use std::sync::Arc;

/// One evaluated output, scoped to an author-chosen graph node and revision.
/// The output component distinguishes multiple bodies produced by one node.
#[derive(Clone, Debug, Eq, PartialEq, Ord, PartialOrd)]
pub struct StageId {
    pub node: String,
    pub output: String,
    pub revision: u64,
}

/// A current-record entity. Its index is meaningful only within `stage`.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct EntityRef {
    pub stage: StageId,
    pub entity: Entity,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum Entity {
    Face(usize),
    Edge(usize),
}

/// The operand position is retained even if the same evaluated stage is used
/// in multiple positions of one operation.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct OperandEntity {
    pub operand: usize,
    pub entity: EntityRef,
}

/// History reported by the operation, or an explicit boundary of knowledge.
/// `Root` only declares an input with no prior stages; it does not assert that
/// its record indices persist across evaluations.
#[derive(Clone, Debug)]
pub enum Evidence {
    Root,
    Reported(history::History),
    Unavailable { reason: String },
}

#[derive(Clone, Debug)]
struct Stage {
    record: Arc<Brep>,
    operands: Vec<StageId>,
    evidence: Evidence,
}

/// A stage-local face origin, with operand indices resolved to exact stages.
/// A merged face can name multiple origins; that is not a spatial partition of
/// the face and says nothing about which portion came from a given origin.
#[derive(Clone, Debug, Eq, PartialEq)]
pub enum FaceOrigin {
    Face(OperandEntity),
    OffsetOf(OperandEntity),
    /// Derived from an operand edge. The operation kind is needed to determine
    /// whether this is a blend, ruled surface, lip, or another construction.
    FromEdge(OperandEntity),
    /// An ordinal in this operation's profile inputs, not a persistent sketch
    /// entity ID. Its numbering rules are defined by the producing operation;
    /// author-level sketch identity requires a separate input mapping.
    ProfileSegment {
        stage: StageId,
        segment: usize,
    },
    Cap {
        stage: StageId,
        end: bool,
    },
}

/// Edge history retains meeting sides separately, rather than combining the
/// origins into an unordered set that would lose which two sides met.
#[derive(Clone, Debug, Eq, PartialEq)]
pub enum EdgeOrigin {
    Edge(OperandEntity),
    Meeting {
        a: Vec<FaceOrigin>,
        b: Vec<FaceOrigin>,
    },
}

/// The operation's direct report. Empty origin lists are retained as reported:
/// they are not interpreted as proof of deletion, creation, or absence.
#[derive(Clone, Debug, Eq, PartialEq)]
pub enum DirectEvidence {
    Root,
    Unavailable {
        reason: String,
    },
    Face {
        change: history::Change,
        origins: Vec<FaceOrigin>,
    },
    Edge {
        incident_faces: Vec<EntityRef>,
        origins: Vec<EdgeOrigin>,
    },
}

/// A history graph that owns result records and shares them with its caller.
/// Insert inputs before their consumers, which prevents cycles. Stages remain
/// separate even when the kernel cannot flatten their histories.
#[derive(Default)]
pub struct HistoryGraph {
    stages: BTreeMap<StageId, Stage>,
}

impl HistoryGraph {
    /// Insert one output and validate the reported history's operand counts,
    /// entity indices, and result edge-to-face incidence against its record.
    /// These structural checks do not prove that the producer's history is
    /// correct or that the record and history came from the same evaluation.
    pub fn insert(
        &mut self,
        id: StageId,
        record: Arc<Brep>,
        operands: Vec<StageId>,
        evidence: Evidence,
    ) -> Result<(), String> {
        if id.node.trim().is_empty() || id.output.trim().is_empty() {
            return Err("stage node and output must be nonempty".into());
        }
        if self.stages.contains_key(&id) {
            return Err("stage already exists".into());
        }
        let counts: Vec<_> = operands
            .iter()
            .map(|id| {
                let s = self.stages.get(id).ok_or("operand stage is unavailable")?;
                Ok((s.record.faces.len(), s.record.edges.len()))
            })
            .collect::<Result<_, &str>>()
            .map_err(str::to_owned)?;
        match &evidence {
            Evidence::Root if !operands.is_empty() => {
                return Err("a root stage cannot have operands".into());
            }
            Evidence::Unavailable { reason } if reason.trim().is_empty() => {
                return Err("unavailable history needs a reason".into());
            }
            Evidence::Reported(history) => {
                history
                    .check_counts((record.faces.len(), record.edges.len()), &counts)
                    .map_err(|e| e.to_string())?;
                for (edge, provenance) in record.edges.iter().zip(&history.edges) {
                    let actual: BTreeSet<_> = edge.uses.iter().map(|u| u.face as usize).collect();
                    let reported: BTreeSet<_> = provenance.faces.iter().copied().collect();
                    if actual != reported {
                        return Err("history edge incidence does not match result record".into());
                    }
                }
            }
            Evidence::Root | Evidence::Unavailable { .. } => {}
        }
        self.stages.insert(
            id,
            Stage {
                record,
                operands,
                evidence,
            },
        );
        Ok(())
    }

    /// Report a single entity's immediate origins, with every operand index
    /// resolved to the corresponding stage and revision. Querying an invalid
    /// stage or entity fails rather than returning an empty origin set.
    pub fn direct_origins(&self, entity: &EntityRef) -> Result<DirectEvidence, String> {
        let stage = self
            .stages
            .get(&entity.stage)
            .ok_or("stage is unavailable")?;
        match entity.entity {
            Entity::Face(i) if i >= stage.record.faces.len() => return Err("invalid face".into()),
            Entity::Edge(i) if i >= stage.record.edges.len() => return Err("invalid edge".into()),
            _ => {}
        }
        match &stage.evidence {
            Evidence::Root => Ok(DirectEvidence::Root),
            Evidence::Unavailable { reason } => Ok(DirectEvidence::Unavailable {
                reason: reason.clone(),
            }),
            Evidence::Reported(history) => match entity.entity {
                Entity::Face(i) => {
                    let face = &history.faces[i];
                    Ok(DirectEvidence::Face {
                        change: face.change,
                        origins: face
                            .origins
                            .iter()
                            .map(|o| Self::face_origin(&entity.stage, stage, *o))
                            .collect(),
                    })
                }
                Entity::Edge(i) => {
                    let edge = &history.edges[i];
                    Ok(DirectEvidence::Edge {
                        incident_faces: edge
                            .faces
                            .iter()
                            .map(|&f| EntityRef {
                                stage: entity.stage.clone(),
                                entity: Entity::Face(f),
                            })
                            .collect(),
                        origins: edge
                            .origins
                            .iter()
                            .map(|origin| match origin {
                                history::EdgeOrigin::Edge { operand, edge } => EdgeOrigin::Edge(
                                    Self::source(stage, *operand, Entity::Edge(*edge)),
                                ),
                                history::EdgeOrigin::Meet { a, b } => EdgeOrigin::Meeting {
                                    a: a.origins()
                                        .iter()
                                        .map(|o| Self::face_origin(&entity.stage, stage, *o))
                                        .collect(),
                                    b: b.origins()
                                        .iter()
                                        .map(|o| Self::face_origin(&entity.stage, stage, *o))
                                        .collect(),
                                },
                            })
                            .collect(),
                    })
                }
            },
        }
    }

    // `insert` checked all operand/entity indices before storing the history.
    fn source(stage: &Stage, operand: usize, entity: Entity) -> OperandEntity {
        OperandEntity {
            operand,
            entity: EntityRef {
                stage: stage.operands[operand].clone(),
                entity,
            },
        }
    }

    fn face_origin(id: &StageId, stage: &Stage, origin: history::FaceOrigin) -> FaceOrigin {
        match origin {
            history::FaceOrigin::Face { operand, face } => {
                FaceOrigin::Face(Self::source(stage, operand, Entity::Face(face)))
            }
            history::FaceOrigin::Offset { operand, face } => {
                FaceOrigin::OffsetOf(Self::source(stage, operand, Entity::Face(face)))
            }
            history::FaceOrigin::Edge { operand, edge } => {
                FaceOrigin::FromEdge(Self::source(stage, operand, Entity::Edge(edge)))
            }
            history::FaceOrigin::Profile { segment } => FaceOrigin::ProfileSegment {
                stage: id.clone(),
                segment,
            },
            history::FaceOrigin::Cap { end } => FaceOrigin::Cap {
                stage: id.clone(),
                end,
            },
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use solidcore_record::brep::history::{Change, EdgeProv, FaceProv, Side};

    fn id(node: &str, revision: u64) -> StageId {
        StageId {
            node: node.into(),
            output: "body".into(),
            revision,
        }
    }

    fn entity(stage: &StageId, entity: Entity) -> EntityRef {
        EntityRef {
            stage: stage.clone(),
            entity,
        }
    }

    fn operand(stage: &StageId, position: usize, item: Entity) -> OperandEntity {
        OperandEntity {
            operand: position,
            entity: entity(stage, item),
        }
    }

    fn box_record() -> Arc<Brep> {
        let body = solidcore_ops::make_box([0., 0., 0.], [10., 10., 10.]).unwrap();
        Arc::new(body.to_record().unwrap().0)
    }

    // A structural fixture: one output record with identity histories from the
    // first operand. Tests below replace selected origins to exercise different
    // relations. Real geometry tests use the separate richer-kernel probe.
    fn identity_history(record: &Brep, operands: usize) -> history::History {
        history::History {
            operands,
            faces: (0..record.faces.len())
                .map(|face| FaceProv {
                    origins: vec![history::FaceOrigin::Face { operand: 0, face }],
                    change: Change::Kept,
                })
                .collect(),
            edges: record
                .edges
                .iter()
                .enumerate()
                .map(|(edge, record)| EdgeProv {
                    faces: record
                        .uses
                        .iter()
                        .map(|u| u.face as usize)
                        .collect::<BTreeSet<_>>()
                        .into_iter()
                        .collect(),
                    origins: vec![history::EdgeOrigin::Edge { operand: 0, edge }],
                })
                .collect(),
        }
    }

    #[test]
    fn cut_meeting_then_blend_remains_explainable_without_flattening() {
        let record = box_record();
        let stock = id("stock", 1);
        let tool = id("tool", 1);
        let cut = id("cut", 1);
        let blend = id("blend", 1);
        let mut graph = HistoryGraph::default();
        for source in [&stock, &tool] {
            graph
                .insert(source.clone(), record.clone(), vec![], Evidence::Root)
                .unwrap();
        }

        let mut cut_history = identity_history(&record, 2);
        cut_history.edges[0].origins = vec![history::EdgeOrigin::meet(
            history::FaceOrigin::Face {
                operand: 0,
                face: 2,
            },
            history::FaceOrigin::Face {
                operand: 1,
                face: 3,
            },
        )];
        graph
            .insert(
                cut.clone(),
                record.clone(),
                vec![stock.clone(), tool.clone()],
                Evidence::Reported(cut_history.clone()),
            )
            .unwrap();

        let mut blend_history = identity_history(&record, 1);
        blend_history.faces[0] = FaceProv {
            origins: vec![history::FaceOrigin::Edge {
                operand: 0,
                edge: 0,
            }],
            change: Change::Generated,
        };
        let mut flattened = blend_history.clone();
        assert!(flattened.substitute(0, &cut_history).is_err());
        graph
            .insert(
                blend.clone(),
                record.clone(),
                vec![cut.clone()],
                Evidence::Reported(blend_history),
            )
            .unwrap();

        assert_eq!(
            graph
                .direct_origins(&entity(&blend, Entity::Face(0)))
                .unwrap(),
            DirectEvidence::Face {
                change: Change::Generated,
                origins: vec![FaceOrigin::FromEdge(operand(&cut, 0, Entity::Edge(0)))]
            }
        );
        let DirectEvidence::Edge { origins, .. } = graph
            .direct_origins(&entity(&cut, Entity::Edge(0)))
            .unwrap()
        else {
            panic!("expected recorded meeting");
        };
        assert_eq!(
            origins,
            vec![EdgeOrigin::Meeting {
                a: vec![FaceOrigin::Face(operand(&stock, 0, Entity::Face(2)))],
                b: vec![FaceOrigin::Face(operand(&tool, 1, Entity::Face(3)))],
            }]
        );
    }

    #[test]
    fn unavailable_and_empty_origins_are_not_claimed_as_generated() {
        let record = box_record();
        let root = id("source", 2);
        let missing = id("unknown", 3);
        let reported = id("reported", 3);
        let mut graph = HistoryGraph::default();
        graph
            .insert(root.clone(), record.clone(), vec![], Evidence::Root)
            .unwrap();
        graph
            .insert(
                missing.clone(),
                record.clone(),
                vec![root.clone()],
                Evidence::Unavailable {
                    reason: "operation did not report history".into(),
                },
            )
            .unwrap();
        assert_eq!(
            graph
                .direct_origins(&entity(&missing, Entity::Edge(0)))
                .unwrap(),
            DirectEvidence::Unavailable {
                reason: "operation did not report history".into()
            }
        );
        let mut history = identity_history(&record, 1);
        history.edges[0].origins.clear();
        graph
            .insert(
                reported.clone(),
                record.clone(),
                vec![root],
                Evidence::Reported(history),
            )
            .unwrap();
        let DirectEvidence::Edge { origins, .. } = graph
            .direct_origins(&entity(&reported, Entity::Edge(0)))
            .unwrap()
        else {
            panic!("expected reported edge");
        };
        assert!(origins.is_empty());
        assert!(graph
            .direct_origins(&entity(&reported, Entity::Face(record.faces.len())))
            .is_err());
    }

    #[test]
    fn repeated_input_retains_each_operand_position() {
        let record = box_record();
        let source = id("source", 7);
        let output = id("operation", 8);
        let mut graph = HistoryGraph::default();
        graph
            .insert(source.clone(), record.clone(), vec![], Evidence::Root)
            .unwrap();
        let mut history = identity_history(&record, 2);
        history.edges[0].origins = vec![history::EdgeOrigin::meet(
            history::FaceOrigin::Face {
                operand: 0,
                face: 1,
            },
            history::FaceOrigin::Face {
                operand: 1,
                face: 2,
            },
        )];
        graph
            .insert(
                output.clone(),
                record,
                vec![source.clone(), source.clone()],
                Evidence::Reported(history),
            )
            .unwrap();
        let DirectEvidence::Edge { origins, .. } = graph
            .direct_origins(&entity(&output, Entity::Edge(0)))
            .unwrap()
        else {
            panic!("expected an edge");
        };
        assert_eq!(
            origins,
            vec![EdgeOrigin::Meeting {
                a: vec![FaceOrigin::Face(operand(&source, 0, Entity::Face(1)))],
                b: vec![FaceOrigin::Face(operand(&source, 1, Entity::Face(2)))],
            }]
        );
    }

    #[test]
    fn merged_and_split_faces_keep_all_local_origins() {
        let record = box_record();
        let left = id("left", 1);
        let right = id("right", 1);
        let merged = id("merged", 1);
        let split = id("split", 2);
        let mut graph = HistoryGraph::default();
        for source in [&left, &right] {
            graph
                .insert(source.clone(), record.clone(), vec![], Evidence::Root)
                .unwrap();
        }
        let mut merge_history = identity_history(&record, 2);
        merge_history.faces[0] = FaceProv {
            change: Change::Merged,
            origins: vec![
                history::FaceOrigin::Face {
                    operand: 0,
                    face: 0,
                },
                history::FaceOrigin::Face {
                    operand: 1,
                    face: 0,
                },
            ],
        };
        graph
            .insert(
                merged.clone(),
                record.clone(),
                vec![left.clone(), right.clone()],
                Evidence::Reported(merge_history),
            )
            .unwrap();
        assert_eq!(
            graph
                .direct_origins(&entity(&merged, Entity::Face(0)))
                .unwrap(),
            DirectEvidence::Face {
                change: Change::Merged,
                origins: vec![
                    FaceOrigin::Face(operand(&left, 0, Entity::Face(0))),
                    FaceOrigin::Face(operand(&right, 1, Entity::Face(0))),
                ]
            }
        );
        let mut split_history = identity_history(&record, 1);
        for face in &mut split_history.faces[..2] {
            *face = FaceProv {
                change: Change::Split,
                origins: vec![history::FaceOrigin::Face {
                    operand: 0,
                    face: 0,
                }],
            };
        }
        graph
            .insert(
                split.clone(),
                record,
                vec![merged.clone()],
                Evidence::Reported(split_history),
            )
            .unwrap();
        for face in 0..2 {
            assert_eq!(
                graph
                    .direct_origins(&entity(&split, Entity::Face(face)))
                    .unwrap(),
                DirectEvidence::Face {
                    change: Change::Split,
                    origins: vec![FaceOrigin::Face(operand(&merged, 0, Entity::Face(0)))]
                }
            );
        }
    }

    #[test]
    fn profile_segments_keep_their_producing_stage() {
        let record = box_record();
        let source = id("source", 1);
        let first = id("first_profile_operation", 4);
        let second = id("second_profile_operation", 4);
        let mut graph = HistoryGraph::default();
        graph
            .insert(source.clone(), record.clone(), vec![], Evidence::Root)
            .unwrap();
        let mut history = identity_history(&record, 1);
        history.faces[0] = FaceProv {
            change: Change::Generated,
            origins: vec![history::FaceOrigin::Profile { segment: 2 }],
        };
        for stage in [&first, &second] {
            graph
                .insert(
                    stage.clone(),
                    record.clone(),
                    vec![source.clone()],
                    Evidence::Reported(history.clone()),
                )
                .unwrap();
        }
        let first_origin = graph
            .direct_origins(&entity(&first, Entity::Face(0)))
            .unwrap();
        let second_origin = graph
            .direct_origins(&entity(&second, Entity::Face(0)))
            .unwrap();
        assert_eq!(
            first_origin,
            DirectEvidence::Face {
                change: Change::Generated,
                origins: vec![FaceOrigin::ProfileSegment {
                    stage: first,
                    segment: 2
                }]
            }
        );
        assert_eq!(
            second_origin,
            DirectEvidence::Face {
                change: Change::Generated,
                origins: vec![FaceOrigin::ProfileSegment {
                    stage: second,
                    segment: 2
                }]
            }
        );
        assert_ne!(first_origin, second_origin);
    }

    #[test]
    fn rejects_missing_stages_wrong_indices_incidence_and_revisions() {
        let record = box_record();
        let source = id("source", 1);
        let mut graph = HistoryGraph::default();
        assert!(graph
            .insert(
                id("orphan", 1),
                record.clone(),
                vec![source.clone()],
                Evidence::Unavailable {
                    reason: "unknown".into()
                }
            )
            .is_err());
        graph
            .insert(source.clone(), record.clone(), vec![], Evidence::Root)
            .unwrap();
        assert!(graph
            .insert(source.clone(), record.clone(), vec![], Evidence::Root)
            .is_err());
        assert!(graph
            .insert(
                id("wrong-revision", 1),
                record.clone(),
                vec![id("source", 2)],
                Evidence::Unavailable {
                    reason: "unknown".into()
                }
            )
            .is_err());
        let mut bad = identity_history(&record, 1);
        bad.faces[0].origins = vec![history::FaceOrigin::Face {
            operand: 0,
            face: record.faces.len(),
        }];
        assert!(graph
            .insert(
                id("bad-index", 1),
                record.clone(),
                vec![source.clone()],
                Evidence::Reported(bad)
            )
            .is_err());
        let mut bad = identity_history(&record, 1);
        bad.edges[0].faces.clear();
        assert!(graph
            .insert(
                id("bad-incidence", 1),
                record.clone(),
                vec![source],
                Evidence::Reported(bad)
            )
            .is_err());
        assert!(Side::new([]).is_none());
    }
}
