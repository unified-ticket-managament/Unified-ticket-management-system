"use client";

import { useEffect, useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import { Mail, MoreHorizontal, Ticket, Workflow } from "lucide-react";

import { cn } from "@/lib/utils";

const ACTIVE_COLOR = "#2563EB";
const INACTIVE_COLOR = "#CBD5E1";
const EASE = [0.4, 0, 0.2, 1] as const; // smooth easeInOut, no bounce/overshoot

type Step = "mail" | "dots" | "workflow" | "ticket";

// Mail -> dots -> Workflow -> dots -> Ticket -> dots -> (loops back to Mail)
const SEQUENCE: Step[] = ["mail", "dots", "workflow", "dots", "ticket", "dots"];

// Per-step hold time before crossfading to the next step. The Workflow step
// holds longer than the others so its rotation actually reads as motion
// rather than a barely-visible tilt.
const STEP_HOLD_MS: Record<Step, number> = {
  mail: 650,
  dots: 500,
  workflow: 1500,
  ticket: 650,
};

export interface WorkflowLoaderProps {
  /** Whether to render the loader. Renders nothing when false. */
  loading: boolean;
  /** Icon size in px. Defaults to 56 (the product's standard loader size). */
  size?: number;
  className?: string;
}

/**
 * Signature inline loading animation for UTMS: a single centered icon that
 * cycles Mail -> ⋯ -> Workflow -> ⋯ -> Ticket -> ⋯ -> Mail, representing the
 * product's own lifecycle (mail intake -> workflow processing -> ticket).
 * Purely presentational — no global state, no popup, no backdrop. Mount it
 * directly inside whatever content area is currently fetching (a card body,
 * a table container, a panel), driven by that surface's own loading flag:
 *
 *   {query.isLoading ? <WorkflowLoader loading /> : <ActualContent />}
 */
export function WorkflowLoader({ loading, size = 56, className }: WorkflowLoaderProps) {
  const [stepIndex, setStepIndex] = useState(0);

  useEffect(() => {
    if (!loading) {
      setStepIndex(0);
      return;
    }

    const step = SEQUENCE[stepIndex];
    const timer = setTimeout(() => {
      setStepIndex((current) => (current + 1) % SEQUENCE.length);
    }, STEP_HOLD_MS[step]);

    return () => clearTimeout(timer);
  }, [loading, stepIndex]);

  if (!loading) {
    return null;
  }

  const step = SEQUENCE[stepIndex];

  return (
    <div
      role="status"
      aria-live="polite"
      aria-label="Loading"
      className={cn("flex min-h-[160px] w-full items-center justify-center py-10", className)}
    >
      <AnimatePresence mode="wait">
        <motion.div
          key={stepIndex}
          initial={{ opacity: 0, scale: 0.82 }}
          animate={{ opacity: 1, scale: 1 }}
          exit={{ opacity: 0, scale: 0.82 }}
          transition={{ duration: 0.32, ease: EASE }}
          style={{ width: size, height: size }}
          className="flex items-center justify-center"
        >
          <StepIcon step={step} size={size} />
        </motion.div>
      </AnimatePresence>
    </div>
  );
}

function StepIcon({ step, size }: { step: Step; size: number }) {
  switch (step) {
    case "mail":
      return <Mail size={size} color={ACTIVE_COLOR} strokeWidth={1.75} />;
    case "ticket":
      return <Ticket size={size} color={ACTIVE_COLOR} strokeWidth={1.75} />;
    case "workflow":
      return (
        <motion.div
          animate={{ rotate: 360 }}
          transition={{ duration: 1.8, repeat: Infinity, ease: "linear" }}
        >
          <Workflow size={size} color={ACTIVE_COLOR} strokeWidth={1.75} />
        </motion.div>
      );
    case "dots":
      return (
        <motion.div
          animate={{ opacity: [0.55, 1, 0.55], scale: [0.95, 1.05, 0.95] }}
          transition={{ duration: 1, repeat: Infinity, ease: EASE }}
        >
          <MoreHorizontal size={size} color={INACTIVE_COLOR} strokeWidth={1.75} />
        </motion.div>
      );
    default:
      return null;
  }
}
