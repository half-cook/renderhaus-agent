# Design fixtures

`account.json` fixes the balance at $42.00. `studio.json` supplies a Demo Studio
project, Demo Creator brief, text and image nodes, one edge, a chat history,
an approval, a timeline revision, an artifact, and empty provider catalogs.
`artifact.svg` is a local 640x360 mock.
No provider job or real user data is used. The playback ticket is fulfilled from
the fixture, including its POST. Other non-GET requests are aborted.

Optional `studio.har` stays ignored. Record only a seeded demo account, scrub
Authorization and Cookie headers, replace signed asset URLs with local fixture
URLs, and replace names and email addresses with Demo Creator and
`demo@example.com`. Never put credentials or signed URLs in evidence. The privacy
guard is a supporting check, not a scrubber or permission to use private data.

The default kit needs no backend and no Clerk keys. Auth captures remain blocked
without Clerk. These fixtures do not satisfy real-backend Comet validation.
