from __future__ import annotations

import importlib
import importlib.util
import math
import unittest
from unittest.mock import patch


class CropPlanTests(unittest.TestCase):
    def plan(self, width=1920, height=1080, aspect="9:16", **params):
        self.assertIsNotNone(importlib.util.find_spec("providers.ffmpeg.reframe"),
                             "Pure crop-plan module is required")
        return importlib.import_module("providers.ffmpeg.reframe").crop_plan(
            width, height, aspect, safe_zone={"top": 0, "bottom": 0, "side": 0}, **params)

    def test_center_windows_for_every_table_aspect(self):
        cases = [("9:16", (656, 0, 606, 1080)), ("1:1", (420, 0, 1080, 1080)),
                 ("4:5", (528, 0, 864, 1080)), ("16:9", (0, 0, 1920, 1080)),
                 ("2.39:1", (0, 138, 1920, 804))]
        for aspect, expected in cases:
            with self.subTest(aspect=aspect):
                p = self.plan(aspect=aspect)
                self.assertEqual(p["mode"], "crop")
                self.assertEqual(tuple(p["crop_box"][n] for n in ("x", "y", "width", "height")), expected)
                self.assertFalse(p["upscaled"])

    def test_native_output_does_not_enlarge_the_cropped_pixels(self):
        p = self.plan()
        self.assertEqual((p["width"], p["height"]), (606, 1076))
        self.assertLessEqual(p["width"], p["crop_box"]["width"])
        self.assertLessEqual(p["height"], p["crop_box"]["height"])

    def test_explicit_upscale_reaches_table_size_and_discloses_no_added_detail(self):
        p = self.plan(allow_upscale=True)
        self.assertEqual((p["width"], p["height"]), (1080, 1920))
        self.assertTrue(p["upscaled"])
        self.assertIn("no added detail", " ".join(p["warnings"]))
        self.assertIn("Topaz", " ".join(p["warnings"]))

    def test_subject_centres_are_static_and_clamped_at_edges(self):
        for subject, expected_x in [({"x": 0, "y": 400, "width": 100, "height": 200}, 0),
                                    ({"x": 1820, "y": 400, "width": 100, "height": 200}, 1314),
                                    ({"x": 900, "y": 400, "width": 100, "height": 200}, 646)]:
            with self.subTest(subject=subject):
                p = self.plan(subject_box=subject)
                self.assertEqual(p["mode"], "crop")
                self.assertEqual(p["crop_box"]["x"], expected_x)

    def test_subject_wider_than_target_switches_to_pad(self):
        p = self.plan(subject_box={"x": 500, "y": 100, "width": 900, "height": 800})
        self.assertEqual(p["mode"], "pad_blur")
        self.assertIsNone(p["crop_box"])
        self.assertIn("safe", " ".join(p["warnings"]).lower())

    def test_asymmetric_safe_zone_shifts_window_and_preserves_subject(self):
        from providers.ffmpeg.reframe import crop_plan
        p = crop_plan(1080, 1920, "1:1", subject_box={"x": 300, "y": 500, "width": 400, "height": 400},
                      safe_zone={"top": .1, "bottom": .3, "side": .05})
        self.assertEqual(p["mode"], "crop")
        c = p["crop_box"]
        self.assertLessEqual(c["y"] + .1*c["height"], 500)
        self.assertGreaterEqual(c["y"] + .7*c["height"], 900)

    def test_impossible_safe_margin_at_frame_edge_uses_pad(self):
        from providers.ffmpeg.reframe import crop_plan
        p = crop_plan(1920, 1080, "9:16", subject_box={"x": 0,"y":100,"width":100,"height":300},
                      safe_zone={"top":.1,"bottom":.2,"side":.1})
        self.assertEqual(p["mode"], "pad_blur")
        b=p["foreground_box"]
        self.assertGreaterEqual(b["x"], p["width"]*.1 - 2)
        self.assertGreaterEqual(b["y"], p["height"]*.1 - 2)
        self.assertLessEqual(b["x"]+b["width"], p["width"]*.9 + 2)
        self.assertLessEqual(b["y"]+b["height"], p["height"]*.8 + 2)

    def test_portrait_rotation_uses_display_coordinates_once(self):
        p = self.plan(1920,1080,"9:16",rotation=90)
        self.assertEqual(p["source_resolution"], "1080x1920")
        self.assertEqual(p["crop_box"], {"x":0,"y":0,"width":1080,"height":1920})
        self.assertEqual((p["width"],p["height"]),(1080,1920))

    def test_extreme_and_odd_sources_remain_even_and_inside_frame(self):
        for w,h in [(2,2),(3,5),(101,99),(16384,2),(2,16384),(1081,1921)]:
            for aspect in ("9:16","1:1","4:5","16:9","2.39:1"):
                with self.subTest(w=w,h=h,aspect=aspect):
                    p=self.plan(w,h,aspect)
                    self.assertGreaterEqual(p["width"],2)
                    self.assertGreaterEqual(p["height"],2)
                    self.assertEqual(p["width"]%2,0)
                    self.assertEqual(p["height"]%2,0)
                    if p["mode"] == "crop":
                        c=p["crop_box"]
                        self.assertTrue(all(v%2==0 for v in c.values()))
                        self.assertLessEqual(c["x"]+c["width"],w)
                        self.assertLessEqual(c["y"]+c["height"],h)

    def test_anchors_choose_frame_edges_without_subject(self):
        self.assertEqual(self.plan(anchor="left")["crop_box"]["x"],0)
        self.assertEqual(self.plan(anchor="right")["crop_box"]["x"],1314)
        self.assertEqual(self.plan(1080,1920,"1:1",anchor="bottom")["crop_box"]["y"],840)

    def test_rounded_canvas_can_be_reused_for_a_second_shot(self):
        from providers.ffmpeg.reframe import crop_plan
        for width, height, aspect in [(320, 180, "2.39:1"), (101, 99, "16:9"), (1081, 1921, "16:9")]:
            with self.subTest(width=width, height=height, aspect=aspect):
                first = self.plan(width, height, aspect)
                second = crop_plan(width, height, aspect, target_size=(first["width"], first["height"]),
                                   safe_zone={"top": 0, "bottom": 0, "side": 0})
                self.assertEqual((second["width"], second["height"]), (first["width"], first["height"]))

    def test_manual_crop_requires_inside_even_geometry_matching_aspect(self):
        box={"x":200,"y":100,"width":800,"height":800}
        self.assertEqual(self.plan(aspect="1:1",crop_box=box)["crop_box"], box)
        for bad in [{**box,"x":-1},{**box,"x":1800},{**box,"width":799},
                    {**box,"height":400},{**box,"width":float("nan")},{**box,"x":True},
                    {**box,"args":"-i"}]:
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                self.plan(aspect="1:1",crop_box=bad)

    def test_invalid_parameters_refused_without_binary_or_io(self):
        for params in [{"rotation":45},{"rotation":float("inf")},{"anchor":"left;exec"},
                       {"allow_upscale":"true"},{"subject_box":{"x":0,"y":0,"width":10**100,"height":100}},
                       {"subject_box":{"x":0,"y":0,"width":100,"height":math.nan}}]:
            with self.subTest(params=params), self.assertRaises(ValueError):
                self.plan(**params)
        for value in (True,0,1,-1,16385,10**100,math.nan,math.inf,"1920"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.plan(width=value)

    def test_safe_zone_config_is_validated_and_used_instead_of_constants(self):
        from providers.ffmpeg.reframe import crop_plan
        for zone in ({"top":.7,"bottom":.4,"side":0},{"side":.5},{"top":math.nan},{"side":-1},
                     {"args":"-vf"}, {"top": .49, "bottom": .49, "side": .49}):
            with self.subTest(zone=zone), self.assertRaises(ValueError):
                crop_plan(1920,1080,"9:16",safe_zone=zone)
        with patch("providers.ffmpeg.reframe.ASPECTS", {"1:1":{"size":[100,100],"safe":{"top":.1,"bottom":.1,"side":.1}}}):
            p=crop_plan(200,100,"1:1",subject_box={"x":0,"y":20,"width":20,"height":20})
        self.assertEqual(p["mode"],"pad_blur")

    def test_shots_split_at_cuts_and_refuse_invalid_or_unbounded_lists(self):
        from providers.ffmpeg.reframe import shots_from_scenes
        self.assertEqual(shots_from_scenes([1,2],3),[
            {"from_s":0,"to_s":1},{"from_s":1,"to_s":2},{"from_s":2,"to_s":3}])
        self.assertEqual(shots_from_scenes([],3),[{"from_s":0,"to_s":3}])
        for times,duration in [([2,1],3),([1,1],3),([-1],3),([4],3),([math.nan],3),
                               ([True],3),(list(range(1,62)),100),([],math.inf),([],601)]:
            with self.subTest(times=times,duration=duration), self.assertRaises(ValueError):
                shots_from_scenes(times,duration)


if __name__ == "__main__":
    unittest.main()
