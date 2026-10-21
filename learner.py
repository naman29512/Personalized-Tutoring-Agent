import json
from pathlib import Path
from llm import agent, URL_FLASH

class MasteryTracker:
    def __init__(self, profile_path="user_profile.json"):
        self.profile_path = Path(profile_path)
        self.data = self.loadp()

    def loadp(self):
        if not self.profile_path.exists():
            return {}
        try:
            with open(self.profile_path, "r") as f:
                return json.load(f)
        except:
            print("profile corrupted")
            return {}

    def savep(self):
        with open(self.profile_path, "w") as f:
            json.dump(self.data, f, indent=4)

    # --- NEW: Python-level fuzzy matcher ---
    def _find_fuzzy_match(self, topic_name: str):
        """Checks if a topic exists, ignoring case, hyphens, and underscores."""
        target = topic_name.lower().replace("-", " ").replace("_", " ").strip()
        for existing_key in self.data.keys():
            existing_clean = existing_key.lower().replace("-", " ").replace("_", " ").strip()
            if target == existing_clean:
                return existing_key
        return None

    def check_topic(self, user_topic: str) -> list:
        """
        Calls the LLM to resolve the user's input against existing database topics.
        Splits compound inputs and splits existing compound database entries if needed.
        """
        existing_topics = list(self.data.keys())
        
        system_prompt = """
        You are a curriculum manager. Compare the user's requested topic against the existing database topics.
        Ensure all topics are ATOMIC (e.g. "AI and ML" -> "Artificial Intelligence" and "Machine Learning").
        
        RULES:
        1. If the user input is a compound topic (e.g. "AI and ML"), break it into a list of atomic topics.
        2. If the user input matches an existing topic (or is a synonym/acronym), use the exact existing name.
        3. If the database currently contains a compound topic (e.g. "AI and ML") and the user is asking about a part of it (e.g. "AI"), you MUST flag the existing compound topic to be split.
        """
        
        schema = {
            "type": "OBJECT",
            "properties": {
                "topics_to_learn": {
                    "type": "ARRAY",
                    "items": {"type": "STRING"},
                    "description": "The atomic topics the user is learning right now."
                },
                "splits_required": {
                    "type": "ARRAY",
                    "items": {
                        "type": "OBJECT",
                        "properties": {
                            "existing_db_topic": {"type": "STRING"},
                            "new_atomic_topics": {"type": "ARRAY", "items": {"type": "STRING"}}
                        }
                    },
                    "description": "Any EXISTING compound topics in the database that need to be permanently split."
                }
            },
            "required": ["topics_to_learn", "splits_required"]
        }
        
        prompt = f"User wants to learn: '{user_topic}'\nCurrently tracked topics in DB: {existing_topics}"
        
        try:
            reply = agent(url=URL_FLASH, prompt=prompt, system_prompt=system_prompt, json_mode=True, schema=schema)
            result = json.loads(reply)
            
            # 1. Execute any required database splits
            for split in result.get("splits_required", []):
                old_topic = split.get("existing_db_topic")
                new_topics = split.get("new_atomic_topics", [])
                
                if old_topic in self.data:
                    prior_score = self.data[old_topic] # Inherit the score
                    del self.data[old_topic]
                    for nt in new_topics:
                        if nt not in self.data:
                            self.data[nt] = prior_score
            
            # 2. Get the list of topics the user is learning right now
            topics_to_learn = result.get("topics_to_learn", [user_topic.strip().title()])
            
            # 3. Ensure all returned topics exist in the DB at baseline 0.2
            for t in topics_to_learn:
                # Use fuzzy match to avoid recreating hyphenated duplicates
                match = self._find_fuzzy_match(t)
                if not match:
                    self.data[t] = 0.2
                    
            self.savep()
            return topics_to_learn
            
        except Exception as e:
            print(f"Topic check failed: {e}")
            t = user_topic.strip().title()
            match = self._find_fuzzy_match(t)
            if not match:
                self.data[t] = 0.2
                self.savep()
                return [t]
            return [match]

    def update_mastery(self, topic, weightage: int, marks_earned: float, type: int):
        # 1. Standardize input to a list
        raw_topics = topic if isinstance(topic, list) else [topic]
        topics_to_update = []

        # 2. Fast-path check: If it already exists exactly (or fuzzy), skip the LLM
        for t in raw_topics:
            existing_match = self._find_fuzzy_match(t)
            
            if existing_match:
                # Python caught it instantly. No API call needed!
                topics_to_update.append(existing_match)
            else:
                # Only call LLM if it's completely new or an acronym/compound
                clean_t = t.strip().title()
                resolved_topics = self.check_topic(clean_t)
                
                # Sanitize whatever the LLM returned just in case it missed the hyphen
                for rt in resolved_topics:
                    rt_match = self._find_fuzzy_match(rt)
                    topics_to_update.append(rt_match if rt_match else rt.strip().title())
                
        # Remove any duplicates in case the LLM returned overlapping topics
        topics_to_update = list(set(topics_to_update))

        updated_scores = {}

        # 3. Loop through all resolved atomic topics and apply BKT math
        for t in topics_to_update:
            if weightage <= 0:
                weightage = 1.0
            
            slip_probability = 0.1 / weightage
            transit_probability = min(0.45, 0.15 * weightage)

            if type == 0:
                guess_probability = 0.25
            elif type == 1:
                guess_probability = 0.05
            else:
                guess_probability = 0.10

            # Failsafe: check_topic sets this, but just in case
            if t not in self.data:
                self.data[t] = 0.2

            cur_topic = self.data[t]
            
            cur_topic_correct = (cur_topic * (1 - slip_probability)) / ((cur_topic * (1 - slip_probability)) + ((1 - cur_topic) * guess_probability))
            cur_topic_wrong = (cur_topic * slip_probability) / ((cur_topic * slip_probability) + ((1 - cur_topic) * (1 - guess_probability)))
            cur_topic = (cur_topic_correct * (marks_earned / weightage)) + ((1 - (marks_earned / weightage)) * cur_topic_wrong)

            self.data[t] = cur_topic + ((1 - cur_topic) * transit_probability)
            self.data[t] = max(0.05, min(0.95, self.data[t]))
            
            updated_scores[t] = self.data[t]

        self.savep()
        
        # 4. Return float if it was a single topic, or dict if multiple topics were processed
        if isinstance(topic, str) and len(updated_scores) == 1:
            return list(updated_scores.values())[0]
        return updated_scores

    def get_profile(self):
        return [sorted(self.data, key=self.data.get), self.data]
        
    def get_weakest_topic(self, default_topic="Core_Programming"):
        if not self.data:
            return default_topic
        return min(self.data, key=self.data.get)