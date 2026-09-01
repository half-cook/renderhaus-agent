import styles from "./Logo.module.css";

/**
 * Renderhaus icon mark -- the actual brand asset (extracted from the
 * source lockup, background cut to transparency), not a hand-drawn
 * approximation. It's white-only, so it always sits on its own small dark
 * chip -- the same presentation the brand deck itself uses -- rather than
 * relying on the surrounding page to be dark.
 */
export function LogoMark({ size = 18 }: { size?: number }) {
  const chip = Math.round(size * 1.6);
  return (
    <span
      className={styles["logo-chip"]}
      style={{ width: chip, height: chip, borderRadius: Math.round(chip * 0.22) }}
    >
      <img src="/renderhaus-mark.png" alt="" width={size} height={size} />
    </span>
  );
}
