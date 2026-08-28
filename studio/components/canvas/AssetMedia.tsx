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
};

export function AssetMedia({ asset, alt, className, controls = false, muted = false }: Props) {
  const source = useStudioAssetPlaybackUrl(asset);
  if (!asset) return null;
  if (!source) {
    return <div className={`${className || ""} media-loading`} aria-label={`Loading ${alt}`} />;
  }
  if (asset.kind === "image") {
    return <img className={className} src={source} alt={alt} />;
  }
  if (asset.kind === "video") {
    return <video className={className} src={source} controls={controls} muted={muted} playsInline />;
  }
  return <audio className={className} src={source} controls={controls} />;
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
