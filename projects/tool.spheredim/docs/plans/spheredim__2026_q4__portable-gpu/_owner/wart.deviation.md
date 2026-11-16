# Deliberate workflow adjustments

## Bounded CPU build and GPU continuation

The blanket heavy-build/GPU serialization rule prevented useful GPU work during a single shader compiler process. Current evidence: compiler RSS 137 MiB, only one compiler, 38,656,636 KiB free, build scratch cap 600 MiB plus continuation cap 512 MiB fitting the 35 GiB reserve. Permit one 1,000-step GPU continuation while this CPU-only build progresses. The build worker holds GPU evaluation until the training worker releases it. Both retain disk guards and separate outputs; no uncontended runtime claim is allowed for this overlapping trial. Revert to serialized GPU execution afterward.
