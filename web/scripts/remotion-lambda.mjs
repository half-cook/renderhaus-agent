import path from "node:path";
import { fileURLToPath } from "node:url";
import {
  deployFunction,
  deploySite,
  getOrCreateBucket,
  getRolePolicy,
  getUserPolicy,
} from "@remotion/lambda";

const scriptDir = path.dirname(fileURLToPath(import.meta.url));
const webRoot = path.resolve(scriptDir, "..");
const command = process.argv[2];
const region = process.env.REMOTION_APP_REGION || process.env.AWS_REGION || "us-east-1";
const requestedLambdaTimeout = Number.parseInt(
  process.env.REMOTION_LAMBDA_TIMEOUT_SECONDS || "600",
  10,
);
const lambdaTimeoutInSeconds = Math.min(
  900,
  Math.max(60, Number.isFinite(requestedLambdaTimeout) ? requestedLambdaTimeout : 600),
);

if (command === "policies") {
  process.stdout.write(
    `RENDERHAUS_REMOTION_POLICIES=${JSON.stringify({
      rolePolicy: JSON.parse(getRolePolicy()),
      userPolicy: JSON.parse(getUserPolicy()),
    })}\n`,
  );
} else if (command === "deploy") {
  const { bucketName } = await getOrCreateBucket({ region });
  const functionResult = await deployFunction({
    region,
    timeoutInSeconds: lambdaTimeoutInSeconds,
    memorySizeInMb: 2048,
    diskSizeInMb: 2048,
    createCloudWatchLogGroup: true,
    cloudWatchLogRetentionPeriodInDays: 14,
  });
  const siteResult = await deploySite({
    region,
    bucketName,
    entryPoint: path.join(webRoot, "src", "remotion", "index.ts"),
    siteName: "renderhaus",
    options: { rootDir: webRoot },
  });
  process.stdout.write(
    `RENDERHAUS_REMOTION_DEPLOYMENT=${JSON.stringify({
      region,
      bucketName,
      functionName: functionResult.functionName,
      functionAlreadyExisted: functionResult.alreadyExisted,
      serveUrl: siteResult.serveUrl,
      siteName: siteResult.siteName,
      siteStats: siteResult.stats,
    })}\n`,
  );
} else {
  process.stderr.write("Usage: node scripts/remotion-lambda.mjs <policies|deploy>\n");
  process.exitCode = 2;
}
