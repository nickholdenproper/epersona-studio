"""Lock in the prompt builder behavior across all three templates."""
DESC = """SHOT_ANGLE: eye-level, medium shot
WOMAN_POSITION: standing tall near a window, arms relaxed at her sides
ACTION_ACTIVITY: posing for the photo
FACIAL_FEATURES: oval face, blue eyes, small nose, full lips
CLOTHING: wearing a red silk dress with thin straps
ENVIRONMENT: a cozy bedroom with a large window
PROPS_OBJECTS: a small vase on the table
LIGHTING: soft natural morning light from the window
SKIN_DETAILS: smooth warm skin
MOOD: confident and calm
SUBJECT_AGE: mid-20s
"""


def test_natural_paragraph(studio):
    studio.prompt_template = "Natural Paragraph"
    out = studio.build_advanced_prompt(DESC, {}, ["#FF5733", "#4A2C1A"])
    assert out.startswith("HAIR:")
    assert "HAIR COLOR:" in out
    assert "HEX VALUES:" in out
    assert "cinematic photo" in out
    assert "red silk dress" in out.lower()


def test_direct_attributes(studio):
    studio.prompt_template = "Direct Attributes"
    out = studio.build_advanced_prompt(DESC, {}, [])
    assert out.startswith("[Body]:")
    assert "[Hair Lock]:" in out
    assert "[Environment]:" in out
    assert "[Lighting]:" in out


def test_soul_2_0(studio):
    studio.prompt_template = "Soul 2.0"
    out = studio.build_advanced_prompt(DESC, {}, [])
    assert out.startswith("Soul:")
    assert "strictly" in out.lower()


def test_rear_facing_strips_face(studio):
    studio.last_pose_gt = {
        "vlm": {
            "FACING": "away from camera",
            "BACK_VISIBLE": "true",
            "POSITION": "standing with her back to the camera",
            "CAMERA_ANGLE": "eye-level",
            "GAZE": "",
        }
    }
    out = studio.build_advanced_prompt(DESC, {}, [])
    assert "NOT facing" in out
    # facial details are stripped when the face isn't visible
    assert "oval face" not in out.lower()
    assert "blue eyes" not in out.lower()


def test_rear_facing_strips_face_direct_attributes(studio):
    studio.prompt_template = "Direct Attributes"
    studio.last_pose_gt = {
        "vlm": {
            "FACING": "away from camera",
            "BACK_VISIBLE": "true",
            "POSITION": "standing with her back to the camera",
            "CAMERA_ANGLE": "eye-level",
            "GAZE": "",
        }
    }
    out = studio.build_advanced_prompt(DESC, {}, [])
    assert "turned away from camera" in out.lower()


def test_rear_facing_looking_back_keeps_face(studio):
    studio.last_pose_gt = {
        "vlm": {
            "FACING": "away from camera",
            "BACK_VISIBLE": "true",
            "POSITION": "standing with her back to the camera",
            "GAZE": "looking back over shoulder at camera",
            "ORIENTATION": "torso away from camera, looking over shoulder",
        }
    }
    out = studio.build_advanced_prompt(DESC, {}, [])
    assert "over her shoulder at the camera" in out
    assert "face is visible" in out


def test_naked_override(studio):
    studio.opt_naked = True
    out = studio.build_advanced_prompt(DESC, {}, [])
    assert "completely naked" in out.lower()


def test_no_default_details(studio):
    studio.use_default_details = False
    out = studio.build_advanced_prompt("Some **bold** text and a # pink wall.", {}, ["#FF5733"])
    assert "bold" not in out
    assert "HEX VALUES:" in out


def test_outfit_override(studio):
    studio.outfit_active = True
    studio.outfit_description = "A fitted black leather jacket and ripped jeans."
    out = studio.build_advanced_prompt(DESC, {}, [])
    assert "leather jacket" in out.lower()
    assert "silk dress" not in out.lower()


def test_short_length_uses_short_hairstyle_phrase(studio):
    studio.hairstyle = "High Ponytail"
    studio.hair_length = 30
    out = studio.build_advanced_prompt(DESC, {}, [])
    assert "micro-ponytail" in out


def test_long_length_uses_full_hairstyle_phrase(studio):
    studio.hairstyle = "High Ponytail"
    studio.hair_length = 78
    out = studio.build_advanced_prompt(DESC, {}, [])
    assert "sleek high ponytail" in out
    assert "micro-ponytail" not in out


def test_hairstyle_phrase_in_soul(studio):
    studio.prompt_template = "Soul 2.0"
    studio.hairstyle = "Curtain Bangs"
    out = studio.build_advanced_prompt(DESC, {}, [])
    assert "curtain bangs" in out.lower()


def test_hairstyle_phrase_in_direct_attributes(studio):
    studio.prompt_template = "Direct Attributes"
    studio.hairstyle = "Fishtail Braid"
    studio.hair_length = 70
    out = studio.build_advanced_prompt(DESC, {}, [])
    assert "fishtail braid" in out.lower()