import json
import os
import sys
import unittest


BLENDER_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if BLENDER_DIR not in sys.path:
    sys.path.insert(0, BLENDER_DIR)

import v2_pipeline as vp


class V2PipelinePlacementModeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.assets = vp.load_assets()

    @staticmethod
    def _plan_key(plan):
        return json.dumps(plan.to_dict(), sort_keys=True)

    def test_default_mode_matches_explicit_legacy(self):
        implicit = vp.generate_accepted(40, 7000, self.assets)
        explicit = vp.generate_accepted(
            40,
            7000,
            self.assets,
            placement_mode="legacy",
        )

        self.assertEqual(implicit[3], explicit[3])
        self.assertEqual(
            [self._plan_key(plan) for plan in implicit[0]],
            [self._plan_key(plan) for plan in explicit[0]],
        )
        self.assertEqual(
            [(reject.reason, reject.detail) for reject in implicit[1]],
            [(reject.reason, reject.detail) for reject in explicit[1]],
        )

    def test_constrained_mode_defers_explicit_occluder_c2(self):
        _, rejects, _, _ = vp.generate_accepted(200, 7000, self.assets)
        c2_reject = next(reject for reject in rejects if reject.reason == "C2")

        legacy = vp.solve_placement(
            c2_reject.spec,
            self.assets,
            placement_mode="legacy",
        )
        constrained = vp.solve_placement(
            c2_reject.spec,
            self.assets,
            placement_mode="constrained",
        )

        self.assertIsInstance(legacy, vp.Reject)
        self.assertEqual("C2", legacy.reason)
        self.assertIsInstance(constrained, vp.Plan)
        self.assertIsNotNone(constrained.occluder)

    def test_unknown_placement_mode_is_rejected(self):
        spec = vp.generate_specs(1, 7000, self.assets)[0][0]
        with self.assertRaisesRegex(ValueError, "placement_mode"):
            vp.solve_placement(spec, self.assets, placement_mode="unknown")

    def test_diagnostic_explicit_fallback_attaches_occluder_without_changing_spec(self):
        plans, _, _, _ = vp.generate_accepted(
            20,
            7500,
            self.assets,
            placement_mode="constrained",
        )
        plan = next(
            item
            for item in plans
            if item.spec.f_target > 0.0 and item.occluder is None
        )

        adjusted = vp.attach_diagnostic_explicit_occluder(
            plan,
            self.assets,
        )

        self.assertIsInstance(adjusted, vp.Plan)
        self.assertIsNotNone(adjusted.occluder)
        self.assertEqual(plan.spec.to_dict(), adjusted.spec.to_dict())
        self.assertEqual(plan.cam_pos, adjusted.cam_pos)
        self.assertEqual(plan.cam_look, adjusted.cam_look)
        self.assertEqual(plan.f_cargo, adjusted.f_cargo)
        self.assertAlmostEqual(plan.spec.f_target, adjusted.f_need)
        self.assertTrue(adjusted.occluder["diagnostic_fallback"])
        self.assertAlmostEqual(
            plan.spec.f_target * adjusted.pallet_silhouette_px2,
            adjusted.occluder["overlap_target_px2"],
        )

    def test_diagnostic_explicit_fallback_is_noop_when_not_needed(self):
        plans, _, _, _ = vp.generate_accepted(
            20,
            7500,
            self.assets,
            placement_mode="constrained",
        )
        zero_target = next(item for item in plans if item.spec.f_target == 0.0)
        with_occluder = next(item for item in plans if item.occluder is not None)

        self.assertIs(
            zero_target,
            vp.attach_diagnostic_explicit_occluder(zero_target, self.assets),
        )
        self.assertIs(
            with_occluder,
            vp.attach_diagnostic_explicit_occluder(with_occluder, self.assets),
        )

    def test_controlled_explicit_proposals_preserve_spec_camera_and_feasible_side(self):
        plans, _, _, _ = vp.generate_accepted(
            20,
            7500,
            self.assets,
            placement_mode="constrained",
        )
        # select by PREDICATE, not by index: the sampler's rng stream is not a stable
        # fixture (it shifts whenever an axis is re-ordered, e.g. the camera-distance cap).
        occluded = [
            plan for plan in plans
            if plan.spec.f_target > 1e-6 and plan.occluder is not None
        ][:3]
        self.assertEqual(3, len(occluded))
        for original in occluded:
            prepared = vp.prepare_diagnostic_explicit_occluders(
                original,
                self.assets,
                max_proposals=3,
            )

            self.assertIsInstance(prepared, vp.Plan)
            self.assertEqual(original.spec.to_dict(), prepared.spec.to_dict())
            self.assertEqual(original.cam_pos, prepared.cam_pos)
            self.assertEqual(original.cam_look, prepared.cam_look)
            self.assertEqual(original.f_cargo, prepared.f_cargo)
            self.assertAlmostEqual(original.spec.f_target, prepared.f_need)
            self.assertIsNotNone(prepared.occluder)

            proposals = [
                prepared.occluder,
                *prepared.occluder["diagnostic_resample_proposals"],
            ]
            self.assertGreaterEqual(len(proposals), 2)
            self.assertLessEqual(len(proposals), 3)
            self.assertEqual(
                1,
                len({proposal["side"] for proposal in proposals}),
            )
            original_side = prepared.occluder[
                "diagnostic_original_side_target"
            ]
            effective_side = vp.diagnostic_explicit_side(
                original_side,
                original.spec.elevation_deg,
                original.spec.f_target,
            )
            self.assertEqual(
                {effective_side},
                {proposal["side"] for proposal in proposals},
            )
            for proposal in proposals:
                self.assertEqual(
                    original_side,
                    proposal["diagnostic_original_side_target"],
                )
                self.assertEqual(
                    effective_side,
                    proposal["diagnostic_effective_side_target"],
                )
                self.assertEqual(
                    effective_side != original_side,
                    proposal["diagnostic_side_feasibility_override"],
                )
            self.assertEqual(
                len(proposals),
                len(
                    {
                        (
                            proposal["obj_name"],
                            tuple(round(value, 8) for value in proposal["center"]),
                            round(proposal["scale"], 8),
                        )
                        for proposal in proposals
                    }
                ),
            )
            for proposal in proposals:
                self.assertAlmostEqual(
                    original.spec.f_target * prepared.pallet_silhouette_px2,
                    proposal["overlap_target_px2"],
                )

    def test_diagnostic_proposal_utility_balances_height_and_filled_silhouette(self):
        utility = getattr(vp, "diagnostic_proposal_utility", None)

        self.assertIsNotNone(utility)
        solid = {
            "bbox_m": [2.0, 1.0, 0.5],
            "bbox_cross_m2": 2.0,
            "fill_ratio": 0.8,
            "scale": 1.0,
        }
        sparse = {
            "bbox_m": [1.0, 2.0, 0.2],
            "bbox_cross_m2": 2.0,
            "fill_ratio": 0.2,
            "scale": 1.0,
        }
        self.assertGreater(utility(solid), utility(sparse))
        self.assertEqual(utility(solid), utility(dict(solid)))

    def test_diagnostic_proposal_selection_preserves_shape_diversity(self):
        select = getattr(vp, "select_diagnostic_explicit_proposals", None)

        self.assertIsNotNone(select)

        def candidate(name, bx, by, bz, fill, nonce):
            return {
                "obj_name": name,
                "bbox_m": [bx, by, bz],
                "bbox_cross_m2": bx * by,
                "fill_ratio": fill,
                "scale": 1.0,
                "diagnostic_proposal_nonce": nonce,
            }

        primary = candidate("primary", 0.3, 0.6, 0.3, 0.6, 0)
        compact_capacity = candidate(
            "compact_capacity", 0.55, 1.1, 0.45, 0.95, 8
        )
        compact_slender = candidate(
            "compact_slender", 0.3, 1.0, 0.4, 0.98, 87
        )
        tallest = candidate("tallest", 0.65, 2.2, 0.2, 0.45, 19)
        largest_utility = candidate(
            "largest_utility", 1.2, 2.0, 0.3, 0.98, 531
        )
        same_name_duplicate = dict(compact_capacity)
        same_name_duplicate["diagnostic_proposal_nonce"] = 9

        selected = select(
            [
                primary,
                largest_utility,
                tallest,
                compact_slender,
                same_name_duplicate,
                compact_capacity,
            ],
            max_proposals=5,
        )

        self.assertEqual(
            [
                "primary",
                "largest_utility",
                "compact_capacity",
                "compact_slender",
                "tallest",
            ],
            [proposal["obj_name"] for proposal in selected],
        )
        self.assertEqual(
            selected,
            select(
                [
                    primary,
                    largest_utility,
                    tallest,
                    compact_slender,
                    same_name_duplicate,
                    compact_capacity,
                ],
                max_proposals=5,
            ),
        )
        self.assertEqual(
            ["primary", "compact_capacity"],
            [
                proposal["obj_name"]
                for proposal in select(
                    [primary, compact_capacity, tallest],
                    max_proposals=2,
                )
            ],
        )

    def test_diagnostic_proposal_selection_keeps_thin_upright_fallback(self):
        select = getattr(vp, "select_diagnostic_explicit_proposals", None)

        self.assertIsNotNone(select)

        def candidate(name, bx, by, bz, fill, nonce):
            return {
                "obj_name": name,
                "bbox_m": [bx, by, bz],
                "bbox_cross_m2": bx * by,
                "fill_ratio": fill,
                "scale": 1.0,
                "diagnostic_proposal_nonce": nonce,
            }

        primary = candidate("primary", 0.3, 0.6, 0.3, 0.6, 0)
        compact_solid = candidate("compact_solid", 0.5, 1.2, 0.4, 0.95, 8)
        thin_upright = candidate("thin_upright", 1.1, 1.3, 0.06, 0.48, 12)
        large_panel = candidate("large_panel", 1.3, 1.6, 0.4, 0.92, 48)

        selected = select(
            [primary, compact_solid, thin_upright, large_panel],
            max_proposals=2,
        )

        self.assertEqual(
            ["primary", "thin_upright"],
            [proposal["obj_name"] for proposal in selected],
        )

    def test_diagnostic_proposal_selection_keeps_tall_shallow_fallback(self):
        select = getattr(vp, "select_diagnostic_explicit_proposals", None)

        self.assertIsNotNone(select)

        def candidate(name, bx, by, bz, fill, nonce):
            return {
                "obj_name": name,
                "bbox_m": [bx, by, bz],
                "bbox_cross_m2": bx * by,
                "fill_ratio": fill,
                "scale": 1.0,
                "diagnostic_proposal_nonce": nonce,
            }

        primary = candidate("primary", 0.3, 0.6, 0.3, 0.6, 0)
        thin_upright = candidate("thin_upright", 1.1, 1.3, 0.06, 0.48, 12)
        compact_capacity = candidate(
            "compact_capacity", 0.55, 1.1, 0.45, 0.95, 8
        )
        compact_slender = candidate(
            "compact_slender", 0.3, 1.0, 0.4, 0.98, 87
        )
        tallest_thick = candidate(
            "tallest_thick", 1.1, 2.1, 0.55, 0.75, 19
        )
        largest_utility = candidate(
            "largest_utility", 1.5, 1.7, 0.4, 0.98, 531
        )
        tall_shallow = candidate(
            "tall_shallow", 0.9, 1.8, 0.22, 0.96, 152
        )

        selected = select(
            [
                primary,
                thin_upright,
                compact_capacity,
                compact_slender,
                tallest_thick,
                largest_utility,
                tall_shallow,
            ],
            max_proposals=6,
        )

        self.assertIn(
            "tall_shallow",
            [proposal["obj_name"] for proposal in selected],
        )

    def test_diagnostic_proposal_selection_keeps_dense_upright_panel(self):
        select = getattr(vp, "select_diagnostic_explicit_proposals", None)

        self.assertIsNotNone(select)

        def candidate(name, bx, by, bz, fill, nonce):
            return {
                "obj_name": name,
                "bbox_m": [bx, by, bz],
                "bbox_cross_m2": bx * by,
                "fill_ratio": fill,
                "scale": 1.0,
                "diagnostic_proposal_nonce": nonce,
            }

        primary = candidate("primary", 0.3, 0.6, 0.3, 0.6, 0)
        thin_upright = candidate("thin_upright", 1.1, 1.3, 0.06, 0.48, 12)
        compact_solid = candidate("compact_solid", 0.5, 1.2, 0.4, 0.95, 8)
        dense_panel = candidate("dense_panel", 1.0, 2.1, 0.25, 0.96, 152)
        tall_sparse = candidate("tall_sparse", 0.7, 2.4, 0.25, 0.45, 19)

        selected = select(
            [primary, compact_solid, tall_sparse, dense_panel, thin_upright],
            max_proposals=4,
        )

        self.assertEqual(
            ["primary", "thin_upright", "dense_panel", "compact_solid"],
            [proposal["obj_name"] for proposal in selected],
        )

    def test_high_elevation_diagnostic_occluder_uses_ground_feasible_side(self):
        choose_side = getattr(vp, "diagnostic_explicit_side", None)

        self.assertIsNotNone(choose_side)
        self.assertEqual("right", choose_side("right", 59.999))
        self.assertEqual("bottom", choose_side("right", 60.0))
        self.assertEqual("bottom", choose_side("left", 75.0))
        self.assertEqual("bottom", choose_side("center", 80.0))
        self.assertEqual("bottom", choose_side("bottom", 73.4))
        self.assertEqual(
            "right",
            choose_side("right", 35.0, target_fraction=0.41),
        )
        self.assertEqual(
            "right",
            choose_side("right", 35.0, target_fraction=0.20),
        )
        self.assertEqual(
            "right",
            choose_side("right", 25.0, target_fraction=0.41),
        )

    def test_high_target_lateral_occluder_uses_bottom_seed_without_relabeling(self):
        choose_seed_side = getattr(
            vp,
            "diagnostic_explicit_seed_side",
            None,
        )

        self.assertIsNotNone(choose_seed_side)
        self.assertEqual(
            "bottom",
            choose_seed_side("right", 35.0, target_fraction=0.41),
        )
        self.assertEqual(
            "right",
            choose_seed_side("right", 35.0, target_fraction=0.20),
        )
        self.assertEqual(
            "right",
            choose_seed_side("right", 25.0, target_fraction=0.41),
        )

        # select by PREDICATE (see the note above): the case under test is a lateral "right"
        # occluder at an elevation/target combination whose PLACEMENT seed must fall back to
        # "bottom" while the audited side stays "right".
        plans, _, _, _ = vp.generate_accepted(
            200,
            7500,
            self.assets,
            placement_mode="constrained",
        )
        original = next(
            plan for plan in plans
            if (plan.occluder or {}).get("side") == "right"
            and 30.0 <= plan.spec.elevation_deg < 60.0
            and plan.spec.f_target >= 0.30
        )
        prepared = vp.prepare_diagnostic_explicit_occluders(
            original,
            self.assets,
            max_proposals=3,
        )
        proposals = [
            prepared.occluder,
            *prepared.occluder["diagnostic_resample_proposals"],
        ]
        self.assertEqual(
            {"right"},
            {proposal["side"] for proposal in proposals},
        )
        self.assertEqual(
            {"bottom"},
            {
                proposal["diagnostic_placement_seed_side"]
                for proposal in proposals
            },
        )
        self.assertTrue(
            all(
                proposal["diagnostic_placement_seed_decoupled"]
                for proposal in proposals
            )
        )

    def test_occluder_nonce_zero_is_exact_default(self):
        plan = vp.generate_accepted(
            20,
            7500,
            self.assets,
            placement_mode="constrained",
        )[0][18]
        default = vp.solve_placement(
            plan.spec,
            self.assets,
            placement_mode="constrained",
        )
        explicit_zero = vp.solve_placement(
            plan.spec,
            self.assets,
            placement_mode="constrained",
            occluder_nonce=0,
        )

        self.assertEqual(self._plan_key(default), self._plan_key(explicit_zero))

    def test_module_remains_bpy_free(self):
        self.assertNotIn("bpy", sys.modules)


if __name__ == "__main__":
    unittest.main()
