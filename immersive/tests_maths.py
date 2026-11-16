from django.test import SimpleTestCase

from immersive.services import storyboard as sb


class MathsVisualPickTests(SimpleTestCase):
    """Maths-book topics must get their own 3-D scene (not the generic flat cards)."""
    CASES = {
        "shapes3d": "Show 3-D shapes. Talk about the flat surface of a cone and the curved surface of a cylinder.",
        "counting": "Count from 1 to 10 objects. How many fingers do you have? Use the abacus.",
        "numline": "Introduce BEFORE and AFTER and arrange the numbers in ascending order.",
        "opposites": "Explain the opposites hot and cold, tall and short.",
        "colours": "Introduce the primary colours red, yellow and blue and the rainbow.",
        "lines": "Draw straight lines and curved lines; vertical, slanting and horizontal lines in the sand pit.",
        "symmetry": "Cut the apple into halves and talk about symmetry.",
        "oddone": "Find the odd one out in each group.",
    }

    def test_each_topic_gets_its_scene(self):
        for vtype, text in self.CASES.items():
            self.assertEqual(sb.pick_visual(text, [])["type"], vtype, text)

    def test_science_and_generic_text_unchanged(self):
        self.assertEqual(sb.pick_visual("The cell has a nucleus and mitochondria.", [])["type"], "cell")
        self.assertEqual(sb.pick_visual("The Mughal empire began in 1526.", [])["type"], "cluster")

    def test_every_type_has_a_colour_and_is_known_to_llm(self):
        for vtype in self.CASES:
            self.assertIn(vtype, sb.PALETTE)
            self.assertIn(vtype, sb.VISUAL_KEYS)
