def build_translation_messages(title: str) -> list[dict]:
    return [
        {
            "role": "system",
            "content": (
                "You are a professional translator. Keep proper names, places, and people in Portuguese, "
                "do not translate them. Translate only generic race terms and numbers/ordinals. "
                "Output only the translated race name with no extra words, punctuation, or quotes."
            )
        },
        {
            "role": "user",
            "content": (
                "Translate this race name from Portuguese to English. "
                "Keep names unchanged, translate only terms like Triathlon, Half Marathon, Trail, Run, "
                "and numbers/ordinals (e.g., 2° -> 2nd). "
                "Return only the translated name and nothing else:\n\n"
                f"{title}"
            )
        }
    ]
