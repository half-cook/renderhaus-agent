"use client";

import { useStudioAssetPlayback, useStudioAssetPlaybackUrl } from "@/lib/assets";
import type { StudioAsset } from "@/lib/types";
import { useEffect, useState, type ReactNode, type Ref, type ReactEventHandler } from "react";

type Props = {
  asset?: StudioAsset;
  alt: string;
  className?: string;
  controls?: boolean;
  muted?: boolean;
  startTime?: number;
  preload?: "none" | "metadata" | "auto";
  videoRef?: Ref<HTMLVideoElement>;
  onTimeUpdate?: ReactEventHandler<HTMLVideoElement>;
  onEnded?: ReactEventHandler<HTMLVideoElement>;
  onError?: ReactEventHandler<HTMLVideoElement>;
  onPlaybackError?: () => void;
  onMetadata?: (metadata: {
    width?: number;
    height?: number;
    durationSeconds?: number;
  }) => void;
};

export function AssetMedia({
  asset,
  alt,
  className,
  controls = false,
  muted = false,
  startTime,
  preload,
  videoRef,
  onTimeUpdate,
  onEnded,
  onError,
  onPlaybackError,
  onMetadata,
}: Props) {
  const [attempt, setAttempt] = useState(0);
  const [failedVersion, setFailedVersion] = useState<string | null>(null);
  const playback = useStudioAssetPlayback(asset, attempt);
  const failed = Boolean(asset && failedVersion === asset.versionId);
  useEffect(() => {
    if (playback.status === "error" || failed) onPlaybackError?.();
  }, [playback.status, failed, onPlaybackError]);
  if (!asset) return null;
  if (playback.status === "error" || failed) {
    return <div className={`${className || ""} media-placeholder`} role="alert">
      <span>{playback.status === "error" ? playback.message : `Could not play ${alt}.`}</span>
      <button type="button" className="rh-btn rh-btn-sm nodrag" onClick={() => {
        setFailedVersion(null);
        setAttempt((value) => value + 1);
      }}>Reload preview</button>
    </div>;
  }
  if (playback.status === "loading") {
    return <div className={`${className || ""} media-loading`} aria-label={`Loading ${alt}`} />;
  }
  const source = playback.url;
  if (asset.kind === "image") {
    return (
      <img
        className={className}
        src={source}
        alt={alt}
        onError={() => setFailedVersion(asset.versionId)}
        onLoad={(event) => {
          const image = event.currentTarget;
          onMetadata?.({ width: image.naturalWidth, height: image.naturalHeight });
        }}
      />
    );
  }
  if (asset.kind === "video") {
    return (
      <video
        ref={videoRef}
        className={className}
        src={source}
        controls={controls}
        muted={muted}
        preload={preload}
        aria-label={alt}
        playsInline
        onTimeUpdate={onTimeUpdate}
        onEnded={onEnded}
        onError={(event) => { setFailedVersion(asset.versionId); onError?.(event); }}
        onLoadedMetadata={(event) => {
          const video = event.currentTarget;
          if (startTime !== undefined && Number.isFinite(startTime) && startTime >= 0) {
            video.currentTime = Math.min(startTime, Number.isFinite(video.duration) ? video.duration : startTime);
          }
          onMetadata?.({
            width: video.videoWidth,
            height: video.videoHeight,
            durationSeconds: Number.isFinite(video.duration) ? video.duration : undefined,
          });
        }}
      />
    );
  }
  return (
    <audio
      className={className}
      src={source}
      controls={controls}
      preload={preload}
      aria-label={alt}
      onError={() => setFailedVersion(asset.versionId)}
      onLoadedMetadata={(event) => {
        const audio = event.currentTarget;
        if (startTime !== undefined && Number.isFinite(startTime) && startTime >= 0) {
          audio.currentTime = Math.min(startTime, Number.isFinite(audio.duration) ? audio.duration : startTime);
        }
        onMetadata?.({
          durationSeconds: Number.isFinite(audio.duration) ? audio.duration : undefined,
        });
      }}
    />
  );
}

export function AssetDownloadLink({
  asset,
  className,
  children,
  ariaLabel,
}: {
  asset?: StudioAsset;
  className?: string;
  children: ReactNode;
  ariaLabel: string;
}) {
  const source = useStudioAssetPlaybackUrl(asset);
  if (!asset || !source) return null;
  return (
    <a className={className} href={source} download={asset.filename} aria-label={ariaLabel} title="Download">
      {children}
    </a>
  );
}
