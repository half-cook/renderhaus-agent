"use client";

import { SignOutButton } from "@clerk/nextjs";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { LogoMark } from "@/components/Logo";
import { useClerkConfigured } from "@/components/StudioAuth";
import { ThemeToggle } from "@/components/canvas/ThemeToggle";
import { createStudioProject, fetchAccount, fetchStudioProjects, type StudioProject } from "@/lib/api";
import type { StudioAccount } from "@/lib/types";
import styles from "./page.module.css";

function formatUsd(cents: number): string {
  return `$${(cents / 100).toFixed(2)}`;
}

function timeAgo(unixSeconds: number): string {
  const minutes = Math.max(0, Math.floor((Date.now() - unixSeconds * 1000) / 60000));
  if (minutes < 1) return "just now";
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  if (days < 30) return `${days}d ago`;
  return new Date(unixSeconds * 1000).toLocaleDateString();
}

export default function DashboardPage() {
  const clerkConfigured = useClerkConfigured();
  const router = useRouter();
  const [account, setAccount] = useState<StudioAccount | null | undefined>(undefined);
  const [projects, setProjects] = useState<StudioProject[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);

  useEffect(() => {
    let cancelled = false;
    void fetchAccount()
      .then((data) => {
        if (!cancelled) setAccount(data);
      })
      .catch(() => {
        // Signed-out or the request failed -- show "unavailable" rather
        // than spinning on "Loading balance…" forever.
        if (!cancelled) setAccount(null);
      });
    void fetchStudioProjects()
      .then((items) => {
        if (!cancelled) setProjects(items);
      })
      .catch((err) => {
        if (!cancelled) {
          setProjects([]);
          setError(err instanceof Error ? err.message : "Could not load projects.");
        }
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const openProject = (id: string) => router.push(`/app?project=${encodeURIComponent(id)}`);

  const newProject = async () => {
    setCreating(true);
    setError(null);
    try {
      const project = await createStudioProject("Untitled");
      router.push(`/app?project=${encodeURIComponent(project.id)}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not create project.");
      setCreating(false);
    }
  };

  return (
    <main className={styles["dashboard"]}>
      <header className={`chrome-header ${styles["dashboard-header"]}`}>
        <div className="header-left">
          <div className="wordmark">
            <LogoMark size={16} />
            Renderhaus
          </div>
        </div>
        <div className="header-right">
          <ThemeToggle />
          {clerkConfigured ? (
            <SignOutButton redirectUrl="/">
              <button type="button" className={styles["dashboard-link-btn"]}>
                Sign out
              </button>
            </SignOutButton>
          ) : null}
        </div>
      </header>

      <div className={styles["dashboard-body"]}>
        <section>
          <div className={styles["dashboard-card-header"]}>
            <h2>Credits</h2>
          </div>
          {account === undefined ? (
            <p className="inspector-note">Loading balance…</p>
          ) : account === null ? (
            <p className="inspector-note">Balance unavailable.</p>
          ) : (
            <>
              <p className={styles["credit-balance-big"]}>{formatUsd(account.balance_cents)}</p>
              {account.recent_ledger.length === 0 ? (
                <p className="inspector-note">No activity yet.</p>
              ) : (
                <ul className={styles["ledger-list"]}>
                  {account.recent_ledger.map((entry) => (
                    <li key={entry.id} className={styles["ledger-row"]}>
                      <span className={styles["ledger-reason"]}>{entry.reason.replaceAll("_", " ")}</span>
                      <span
                        className={`${styles["ledger-delta"]} ${entry.delta < 0 ? styles.negative : styles.positive}`}
                      >
                        {entry.delta < 0 ? "-" : "+"}
                        {formatUsd(Math.abs(entry.delta))}
                      </span>
                      <span className={styles["ledger-time"]}>{timeAgo(entry.created_at)}</span>
                    </li>
                  ))}
                </ul>
              )}
            </>
          )}
        </section>

        <section>
          <div className={styles["dashboard-card-header"]}>
            <h2>Projects</h2>
            <button
              type="button"
              className={styles["dashboard-link-btn"]}
              onClick={() => void newProject()}
              disabled={creating}
            >
              {creating ? "Creating…" : "+ New project"}
            </button>
          </div>
          {projects === null ? (
            <p className="inspector-note">Loading projects…</p>
          ) : projects.length === 0 ? (
            <p className="inspector-note">No projects yet — start one above.</p>
          ) : (
            <div className={styles["project-grid"]}>
              {projects.map((project) => (
                <button
                  key={project.id}
                  type="button"
                  className={styles["project-card"]}
                  onClick={() => openProject(project.id)}
                >
                  <span className={styles["project-card-name"]}>{project.name}</span>
                  {project.updated_at ? (
                    <span className={styles["project-card-meta"]}>Edited {timeAgo(project.updated_at)}</span>
                  ) : null}
                </button>
              ))}
            </div>
          )}
          {error ? <p className="generate-hint">{error}</p> : null}
        </section>
      </div>
    </main>
  );
}
