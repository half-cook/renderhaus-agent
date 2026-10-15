import pytest

from agent.deep_agent.routing import route_intent


@pytest.mark.parametrize('prompt', [
    'Make a Lottie loading animation of our app icon for the iOS and web onboarding screen',
    'Animate this SVG checkmark as a success Lottie with ease-in-out and a transparent background',
    'Create a transparent loading icon for our app UI',
    'Animate our logo as JSON for the website UI',
    'Create a dotLottie empty state for Android',
    'Make an onboarding animation for our app UI',
])
def test_lottie_routes_to_local_author(prompt):
    route = route_intent(prompt)
    assert (route.skill, route.alias, route.tool) == (
        'lottie-animation', 'lottie_author', 'Lottie___lottie_author')
    assert route.dispatch_tool == 'call_editor_tool'
    assert 'fee' not in route.disclosure.lower()


@pytest.mark.parametrize('prompt,skill', [
    ('Make an MP4 title card for our website', 'motion-graphics'),
    ('Create a lower third for our product launch', 'motion-graphics'),
    ('animate our logo', 'i2v'),
    ('Animate our logo for a video', 'i2v'),
    ('Generate an SVG app icon', 'image-gen'),
    ('Create a title card with the words "Lottie UI"', 'motion-graphics'),
])
def test_existing_deliverables_keep_their_route(prompt, skill):
    route = route_intent(prompt)
    assert route.skill == skill
    assert route.skill != 'lottie-animation'


def test_preview_mp4_does_not_require_final_video_render():
    from agent.studio_agent_next import _requests_video_deliverable

    assert not _requests_video_deliverable('Create a Lottie loader with an MP4 preview')
    assert _requests_video_deliverable('Make an MP4 title card for our website')


def test_vector_output_blocks_video_tools_but_can_source_a_vector():
    from agent.deep_agent.routing import request_tool_blocker

    prompt = 'Make a Lottie loading animation for our app UI'
    assert request_tool_blocker(prompt, 'Remotion___render_timeline')
    assert request_tool_blocker(prompt, 'Fal___generate_wan3_t2v')
    assert request_tool_blocker(prompt, 'Fal___recraft_text_to_vector') is None


@pytest.mark.parametrize('prompt', [
    'Animate a loader for our app UI, but no Lottie',
    'Animate our logo as JSON for the website UI, without Lottie',
    'Do not use Lottie for the website UI animation',
    "Create a loading animation for our app UI, don't use Lottie",
    'Create a loading animation for our app UI, don’t use Lottie',
    'Create a loading animation for our app UI, no need for Lottie',
])
def test_explicit_animation_format_exclusion_is_preserved(prompt):
    assert route_intent(prompt).skill != 'lottie-animation'


@pytest.mark.parametrize('exclusion', [
    'no MP4', "don't export an MP4", 'don’t render a video', 'no need for MP4',
])
def test_negated_video_export_keeps_explicit_lottie_output(exclusion):
    assert route_intent('Create a Lottie loader for our app, ' + exclusion).skill == 'lottie-animation'
