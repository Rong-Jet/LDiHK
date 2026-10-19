from __future__ import annotations

import unittest

from backend.ingestion.worker import stored_source_path


class StoredSourcePathTests(unittest.TestCase):
    def test_chat_folders_lose_the_other_persons_username(self):
        stored = stored_source_path("your_instagram_activity/messages/inbox/somefriend_17845501578508378/message_1.json")
        self.assertNotIn("somefriend", stored)
        self.assertRegex(stored, r"^your_instagram_activity/messages/inbox/conversation-[0-9a-f]{16}/message_1\.json$")

    def test_each_chat_keeps_its_own_path(self):
        first = stored_source_path("messages/inbox/alice_1/message_1.json")
        second = stored_source_path("messages/inbox/bob_2/message_1.json")
        self.assertNotEqual(first, second)
        self.assertEqual(first, stored_source_path("messages/inbox/alice_1/message_1.json"))
        self.assertIn("message_requests/conversation-", stored_source_path("messages/message_requests/carol_3/message_1.json"))

    def test_other_paths_are_unchanged(self):
        for path in (
            "Takeout/YouTube und YouTube Music/Verlauf/Wiedergabeverlauf.json",
            "your_instagram_activity/likes/liked_posts.json",
            "Takeout/YouTube und YouTube Music/Livechats/Livechats(6).csv",
        ):
            self.assertEqual(stored_source_path(path), path)


if __name__ == "__main__":
    unittest.main()
