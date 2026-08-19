"use client";

import type { JsonSchema } from "@/lib/types";

const PROMPT_FIELDS = new Set(["prompt", "text", "lyrics", "script", "style_prompt"]);
const OPAQUE_FIELDS = new Set([
  "title",
  "name",
  "filename",
  "content_b64",
  "image_path_or_url",
  "job_id",
  "song_id",
  "upload_audio_id",
  "upload_file_id",
  "instrumental_id",
  "reference_id",
  "vocal_id",
  "melody_id",
  "audio_url",
]);

type Props = {
  schema: JsonSchema;
  values: Record<string, unknown>;
  options?: Record<string, Array<string | number>>;
  onChange: (name: string, value: unknown) => void;
};

function isOpaqueField(name: string): boolean {
  if (OPAQUE_FIELDS.has(name)) {
    return true;
  }
  return name.endsWith("_id") || name.endsWith("_url") || name.endsWith("_path");
}

function choicesFor(
  name: string,
  field: JsonSchema,
  options?: Record<string, Array<string | number>>,
): Array<string | number> {
  if (PROMPT_FIELDS.has(name) || isOpaqueField(name)) {
    return [];
  }
  const catalog = options?.[name];
  if (catalog && catalog.length > 0) {
    return catalog;
  }
  if (field.enum && field.enum.length > 0) {
    return field.enum.filter((value): value is string | number => typeof value !== "boolean");
  }
  return [];
}

function coerceChoice(
  raw: string,
  field: JsonSchema,
  choices: Array<string | number>,
): unknown {
  if (raw === "") {
    return undefined;
  }
  if (field.type === "integer") {
    return Number.parseInt(raw, 10);
  }
  if (field.type === "number" || typeof choices[0] === "number") {
    return Number(raw);
  }
  return raw;
}

export function SchemaForm({ schema, values, options, onChange }: Props) {
  const properties = schema.properties || {};
  const required = new Set(schema.required || []);
  const names = [
    ...Object.keys(properties).filter((name) => required.has(name)),
    ...Object.keys(properties).filter((name) => !required.has(name)),
  ];

  return (
    <>
      {names.map((name) => {
        const field = properties[name];
        const requiredMark = required.has(name) ? <span className="req">required</span> : null;
        const value = values[name];
        const choices = choicesFor(name, field, options);

        if (field.type === "boolean") {
          return (
            <label className="field check" key={name}>
              <input
                type="checkbox"
                checked={Boolean(value)}
                onChange={(event) => onChange(name, event.target.checked)}
              />
              <span>
                {name}
                {requiredMark}
              </span>
            </label>
          );
        }

        if (choices.length > 0) {
          const selected = value === undefined || value === null ? "" : String(value);
          const extras =
            selected && !choices.some((choice) => String(choice) === selected) ? [value as string | number] : [];
          return (
            <label className="field" key={name}>
              <span>
                {name}
                {requiredMark}
              </span>
              <select
                value={selected}
                onChange={(event) => onChange(name, coerceChoice(event.target.value, field, choices))}
              >
                <option value="">unset</option>
                {[...choices, ...extras].map((option) => (
                  <option key={String(option)} value={String(option)}>
                    {String(option)}
                  </option>
                ))}
              </select>
            </label>
          );
        }

        if (field.type === "integer" || field.type === "number") {
          return (
            <label className="field" key={name}>
              <span>
                {name}
                {requiredMark}
              </span>
              <input
                type="number"
                step={field.type === "integer" ? 1 : "any"}
                value={value === undefined || value === null ? "" : String(value)}
                onChange={(event) => {
                  const raw = event.target.value;
                  if (raw === "") {
                    onChange(name, undefined);
                    return;
                  }
                  onChange(name, field.type === "integer" ? Number.parseInt(raw, 10) : Number(raw));
                }}
              />
            </label>
          );
        }

        if (PROMPT_FIELDS.has(name)) {
          return (
            <label className="field" key={name}>
              <span>
                {name}
                {requiredMark}
              </span>
              <textarea
                value={String(value ?? "")}
                placeholder={field.description || name}
                onChange={(event) => onChange(name, event.target.value)}
              />
            </label>
          );
        }

        return (
          <label className="field" key={name}>
            <span>
              {name}
              {requiredMark}
            </span>
            <input
              value={String(value ?? "")}
              placeholder={field.description || name}
              onChange={(event) => onChange(name, event.target.value)}
            />
          </label>
        );
      })}
    </>
  );
}
