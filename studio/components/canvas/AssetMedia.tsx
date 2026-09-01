"use client";

import { useStudioAssetPlaybackUrl } from "@/lib/assets";
import type { StudioAsset } from "@/lib/types";
import type { ReactNode } from "react";

type Props = {
  asset?: StudioAsset;
  alt: string;
  className?: string;
  controls?: boolean;
  muted?: boolean;
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
  onMetadata,
}: Props) {
  const source = useStudioAssetPlaybackUrl(asset);
  if (!asset) return null;
  if (!source) {
    return <div className={`${className || ""} media-loading`} aria-label={`Loading ${alt}`} />;
  }
  if (asset.kind === "image") {
    return (
      <img
        className={className}
        src={source}
        alt={alt}
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
        className={className}
        src={source}
        controls={controls}
        muted={muted}
        playsInline
        onLoadedMetadata={(event) => {
          const video = event.currentTarget;
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
      onLoadedMetadata={(event) => {
        const audio = event.currentTarget;
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
