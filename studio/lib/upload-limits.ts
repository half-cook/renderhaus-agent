import defaults from "../../configs/studio-upload-limits.json";

const MB = 1024 * 1024;
const mediaSuffixes = {
  image: ["png", "jpg", "jpeg", "webp", "gif", "svg"],
  video: ["mp4", "webm", "mov", "m4v"],
  audio: ["mp3", "wav", "m4a", "ogg", "flac"],
};

export type UploadKind = keyof typeof mediaSuffixes;
export type UploadLimits = Record<UploadKind, number>;
const kinds: UploadKind[] = ["image", "video", "audio"];

export function configuredUploadLimits(env: NodeJS.ProcessEnv): UploadLimits {
  const limits = { ...defaults.max_upload_mb_by_kind };
  const read = (name: string, fallback: number): number => {
    const value = env[name]?.trim();
    if (!value) return fallback;
    const number = Number(value);
    if (!/^[0-9]+$/.test(value) || !Number.isSafeInteger(number) || number <= 0) {
      throw new Error(`${name} must be a positive integer in MB.`);
    }
    return number;
  };
  for (const kind of kinds) {
    limits[kind] = read(
      `STUDIO_MAX_${kind.toUpperCase()}_UPLOAD_MB`,
      read("STUDIO_MAX_UPLOAD_MB", limits[kind]),
    );
  }
  return limits;
}

export function proxyUploadLimitBytes(env: NodeJS.ProcessEnv): number {
  return (Math.max(...Object.values(configuredUploadLimits(env))) + defaults.multipart_overhead_mb) * MB;
}

export function uploadKind(filename: string): UploadKind | null {
  const suffix = filename.includes(".") ? filename.split(".").pop()?.toLowerCase() : "";
  return kinds.find((kind) => mediaSuffixes[kind].includes(suffix || "")) || null;
}

export function parseUploadLimits(value: unknown): UploadLimits {
  if (!value || typeof value !== "object" || !("max_upload_mb_by_kind" in value)) {
    throw new Error("Could not check upload limits. Please try again.");
  }
  const limits = value.max_upload_mb_by_kind;
  if (!limits || typeof limits !== "object" ||
    !("image" in limits) || !("video" in limits) || !("audio" in limits)) {
    throw new Error("Could not check upload limits. Please try again.");
  }
  const validLimit = (limit: unknown): limit is number =>
    typeof limit === "number" && Number.isSafeInteger(limit) && limit > 0;
  if (!validLimit(limits.image) || !validLimit(limits.video) || !validLimit(limits.audio)) {
    throw new Error("Could not check upload limits. Please try again.");
  }
  return { image: limits.image, video: limits.video, audio: limits.audio };
}

export function uploadSizeError(limitMb: number): string {
  return `File is larger than ${limitMb} MB.`;
}

export function checkUploadSize(size: number, limitMb: number): void {
  if (size > limitMb * MB) throw new Error(uploadSizeError(limitMb));
}
