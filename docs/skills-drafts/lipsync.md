# lipsync provider reference

Converted into [the installed lipsync skill](../../agent/deep_agent/skills/lipsync/SKILL.md).
`sync3_lipsync` now binds `Sync___lipsync_video` with `Sync___get_video_task` polling.
The default host is fal; authorized direct Sync is optional. See [SYNC.md](../SYNC.md).

Existing footage plus new audio uses sync-3. Script-only input first needs authorized
ElevenLabs speech and source footage. New generated talking shots use Seedance.
Over-30-second presenters/digital twins still select pending `heygen_avatar_v`, unless
Sync is explicitly requested. LivePortrait/LatentSync remain retired: no InsightFace
non-commercial weights are loaded. All Sync outputs have `training_eligible=false`.
