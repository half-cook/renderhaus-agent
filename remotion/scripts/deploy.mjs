import {deploySite} from '@remotion/lambda';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {randomUUID} from 'node:crypto';
const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const region = process.env.REMOTION_APP_REGION;
const bucketName = process.env.REMOTION_APP_BUCKET_NAME;
if (!region || !bucketName) throw new Error('Existing Remotion region and bucket are required.');
// A versioned site leaves existing renders and the old deployment usable.
const siteName = process.env.REMOTION_SITE_NAME || `renderhaus-timeline-${Date.now()}-${randomUUID().slice(0, 8)}`;
const result = await deploySite({region, bucketName, siteName, entryPoint: path.join(root, 'src/index.ts'), options: {rootDir: root}});
console.log(JSON.stringify({serveUrl: result.serveUrl, siteName: result.siteName}));
