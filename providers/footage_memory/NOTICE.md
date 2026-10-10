# Footage memory pattern attribution

The build/query split and Root > SuperEvent > MacroEvent > Subgraph hierarchy
adapt design ideas from [QwenLM/Qwen-MM-Plugins](https://github.com/QwenLM/Qwen-MM-Plugins)
at commit `e469e92dcd662ab0c4adc798fc50a094c832bfc0`.
The source project uses the [Apache License 2.0](https://github.com/QwenLM/Qwen-MM-Plugins/blob/e469e92dcd662ab0c4adc798fc50a094c832bfc0/LICENSE).
Read date was 2026-10-10.

The source files reviewed were the omni-memory build, storage and store-writer
modules, video-memory schema, query and chunk-merge modules, and
`tests/test_build_memory.py` and `tests/test_build_merge.py`.
No source code file, prompt, fixture, media or model weight from that project
was copied or vendored. Renderhaus implements the shared SQLite schema,
project isolation, deterministic retrieval and verification state itself.

The optional sqlite-vec extension is independently installed and is not
vendored. Its upstream licence is
[MIT or Apache-2.0](https://github.com/asg017/sqlite-vec), read 2026-10-10.
