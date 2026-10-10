"use client";

import { CircleCheckIcon, CircleXIcon, InfoIcon, LoaderCircleIcon, TriangleAlertIcon } from "lucide-react";
import { Toaster as Sonner, type ToasterProps } from "sonner";
import { cn } from "@/lib/cn";

function Toaster({ className, style, toastOptions, ...props }: ToasterProps) {
  return (
    <Sonner
      data-slot="toaster"
      position="bottom-right"
      className={cn("font-sans", className)}
      icons={{
        success: <CircleCheckIcon className="size-4 text-ok" />,
        info: <InfoIcon className="size-4 text-text" />,
        warning: <TriangleAlertIcon className="size-4 text-warn" />,
        error: <CircleXIcon className="size-4 text-danger" />,
        loading: <LoaderCircleIcon className="size-4 text-muted" />,
      }}
      style={{ ...style, zIndex: "var(--z-menu)" }}
      toastOptions={{
        ...toastOptions,
        unstyled: true,
        classNames: {
          toast: "flex items-center gap-3 border border-line bg-node p-4 text-text rounded-none [box-shadow:var(--shadow)]",
          title: "text-sm font-medium",
          description: "text-sm text-muted",
          actionButton: "rounded-none! border! border-line! bg-primary! px-3 py-1.5 text-primary-foreground! text-sm! focus-visible:outline-2 focus-visible:outline-ring",
          cancelButton: "rounded-none! border! border-line! bg-chrome! px-3 py-1.5 text-text! text-sm! focus-visible:outline-2 focus-visible:outline-ring",
          closeButton: "rounded-none! border-line! bg-node! text-text! [box-shadow:var(--shadow)]! focus-visible:outline-2 focus-visible:outline-ring",
          ...toastOptions?.classNames,
        },
      }}
      {...props}
    />
  );
}

export { Toaster };
