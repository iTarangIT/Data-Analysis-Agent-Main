"use client";

import dynamic from "next/dynamic";
import { useSyncExternalStore } from "react";

import { usePrefersReducedMotion } from "@/lib/use-reduced-motion";
import { cn } from "@/lib/utils";

/**
 * The agent's mark: a live WebGL orb, or a still one.
 *
 * three.js is a heavy module that means nothing on the server, so the orb is loaded on the
 * client only and the still version stands in until it arrives. The still one is also what a
 * reader who asked for less motion gets, and what a browser without WebGL gets.
 *
 * Its two colours are read from the palette's custom properties at runtime rather than
 * restated here, so the orb cannot drift from globals.css.
 */

const Orb = dynamic(() => import("@/components/ui/orb").then((module) => module.Orb), {
  ssr: false,
  loading: () => <Still />,
});

type Setup = { colors: [string, string] } | null;

let setup: Setup | undefined;

/** Read once: whether WebGL exists, and the two brand colours. Cached so the snapshot is stable. */
function readSetup(): Setup {
  if (setup !== undefined) return setup;
  try {
    const canvas = document.createElement("canvas");
    const gl = canvas.getContext("webgl2") ?? canvas.getContext("webgl");
    // Probing costs a context; hand it straight back rather than hold one of the browser's few.
    gl?.getExtension("WEBGL_lose_context")?.loseContext();
    const style = getComputedStyle(document.documentElement);
    const soft = style.getPropertyValue("--brand-soft").trim();
    const brand = style.getPropertyValue("--brand").trim();
    setup = gl && soft && brand ? { colors: [soft, brand] } : null;
  } catch {
    setup = null;
  }
  return setup;
}

const noSubscription = () => () => {};

export function AgentOrb({
  thinking = false,
  className,
}: {
  thinking?: boolean;
  className?: string;
}) {
  const reduced = usePrefersReducedMotion();
  const drawable = useSyncExternalStore(noSubscription, readSetup, () => null);

  return (
    <span aria-hidden className={cn("relative block shrink-0", className)}>
      {reduced || !drawable ? (
        <Still />
      ) : (
        <Orb
          colors={drawable.colors}
          agentState={thinking ? "thinking" : null}
          className="size-full"
        />
      )}
    </span>
  );
}

function Still() {
  return (
    <span className="block size-full rounded-full bg-radial-[at_35%_30%] from-brand-soft to-brand/70" />
  );
}
