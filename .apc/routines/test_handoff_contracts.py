import pathlib
import unittest


class HandoffToolsTest(unittest.TestCase):
    def test_agents_can_route_cards_but_cannot_spawn_comment_consultations(self):
        agents = pathlib.Path(__file__).resolve().parents[1] / "agents"
        paths = list(agents.glob("*.md"))
        self.assertEqual(len(paths), 9)
        for path in paths:
            with self.subTest(agent=path.stem):
                meta = path.read_text().split("---", 2)[1]
                line = next(line for line in meta.splitlines() if line.startswith("tools: "))
                tools = {name.strip() for name in line.removeprefix("tools: ").split(",")}
                self.assertTrue({"task_get", "task_update"} <= tools)
                self.assertTrue({"tasks", "task_comment"}.isdisjoint(tools))


if __name__ == "__main__":
    unittest.main()
