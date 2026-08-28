"use client";

import type { JsonSchema } from "@/lib/types";
import { fieldLabel, isPromptField } from "@/lib/canvas/field-labels";
import { choiceLabel } from "@/lib/canvas/model-labels";

const OPAQUE_FIELDS = new Set([
  "filename",
  "content_b64",
  "job_id",
  "song_id",
  "upload_audio_id",
  "upload_file_id",
  "instrumental_id",
  "reference_id",
  "vocal_id",
  "melody_id",
  "audio_url",
  "path",
]);

type Props = {
  schema: JsonSchema;
  values: Record<string, unknown>;
  options?: Record<string, Array<string | number>>;
  hiddenFields?: string[];
  onlyFields?: string[];
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
  if (isPromptField(name) || isOpaqueField(name)) {
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

function coerceChoice(raw: string, field: JsonSchema, choices: Array<string | number>): unknown {
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

export function SchemaForm({ schema, values, options, hiddenFields, onlyFields, onChange }: Props) {
  const properties = schema.properties || {};
  const required = new Set(schema.required || []);
  const hidden = new Set(hiddenFields || []);
  const allow = onlyFields ? new Set(onlyFields) : null;
  const names = [
    ...Object.keys(properties).filter((name) => required.has(name)),
    ...Object.keys(properties).filter((name) => !required.has(name)),
  ].filter((name) => !hidden.has(name) && (!allow || allow.has(name)));

  return (
    <>
      {names.map((name) => {
        const field = properties[name];
        const requiredMark = required.has(name) ? <span className="req">Required</span> : null;
        const value = values[name];
        const choices = choicesFor(name, field, options);
        const label = fieldLabel(name);
        const empty =
          value === undefined ||
          value === null ||
          value === "" ||
          (typeof value === "string" && !value.trim());
        const needsInput = required.has(name) && empty;

        if (field.type === "boolean") {
          return (
            <label className="field check" key={name}>
              <input
                type="checkbox"
                checked={Boolean(value)}
                onChange={(event) => onChange(name, event.target.checked)}
              />
              <span>
                {label}
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
            <label className={`field ${needsInput ? "needs-input" : ""}`} key={name}>
              <span>
                {label}
                {requiredMark}
              </span>
              <div className="field-pill-row" role="radiogroup" aria-label={label}>
                {[...choices, ...extras].map((option) => {
                  const optionValue = String(option);
                  return (
                    <button
                      key={optionValue}
                      type="button"
                      role="radio"
                      aria-checked={selected === optionValue}
                      className={`field-pill${selected === optionValue ? " selected" : ""}`}
                      onClick={() => onChange(name, coerceChoice(optionValue, field, choices))}
                    >
                      {choiceLabel(name, optionValue)}
                    </button>
                  );
                })}
              </div>
            </label>
          );
        }

        if (field.type === "integer" || field.type === "number") {
          return (
            <label className={`field ${needsInput ? "needs-input" : ""}`} key={name}>
              <span>
                {label}
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

        if (isPromptField(name)) {
          return (
            <label className={`field ${needsInput ? "needs-input" : ""}`} key={name}>
              <span>
                {label}
                {requiredMark}
              </span>
              <textarea
                value={String(value ?? "")}
                placeholder={field.description || `Write a ${label.toLowerCase()}`}
                onChange={(event) => onChange(name, event.target.value)}
              />
            </label>
          );
        }

        return (
          <label className={`field ${needsInput ? "needs-input" : ""}`} key={name}>
            <span>
              {label}
              {requiredMark}
            </span>
            <input
              value={String(value ?? "")}
              placeholder={field.description || label}
              onChange={(event) => onChange(name, event.target.value)}
            />
          </label>
        );
      })}
    </>
  );
}
