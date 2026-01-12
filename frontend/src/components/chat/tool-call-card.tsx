"use client";

import Image from "next/image";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui";
import type { ToolCall, ToolContentPart } from "@/types";
import { Wrench, CheckCircle, Loader2, AlertCircle } from "lucide-react";
import { cn } from "@/lib/utils";
import { CopyButton } from "./copy-button";

interface ToolCallCardProps {
  toolCall: ToolCall;
}

/**
 * Check if the result is an array of ToolContentPart objects
 */
function isToolContentArray(result: unknown): result is ToolContentPart[] {
  if (!Array.isArray(result)) return false;
  if (result.length === 0) return false;
  return result.every(
    (item) =>
      typeof item === "object" &&
      item !== null &&
      "type" in item &&
      (item.type === "text" || item.type === "image")
  );
}

/**
 * Get text-only content from result for copy button
 */
function getTextContent(result: unknown): string {
  if (typeof result === "string") return result;
  if (isToolContentArray(result)) {
    return result
      .filter((part): part is { type: "text"; text: string } => part.type === "text")
      .map((part) => part.text)
      .join("\n");
  }
  return JSON.stringify(result, null, 2);
}

export function ToolCallCard({ toolCall }: ToolCallCardProps) {
  const statusConfig = {
    pending: { icon: Loader2, color: "text-muted-foreground", animate: true },
    running: { icon: Loader2, color: "text-blue-500", animate: true },
    completed: { icon: CheckCircle, color: "text-green-500", animate: false },
    error: { icon: AlertCircle, color: "text-red-500", animate: false },
  };

  const { icon: StatusIcon, color, animate } = statusConfig[toolCall.status];

  const argsText = JSON.stringify(toolCall.args, null, 2);
  const resultText = toolCall.result !== undefined ? getTextContent(toolCall.result) : "";

  // Check if result contains images
  const hasImages =
    isToolContentArray(toolCall.result) &&
    toolCall.result.some((part) => part.type === "image");

  return (
    <Card className="bg-muted/50">
      <CardHeader className="py-2 px-3">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Wrench className="h-4 w-4 text-muted-foreground" />
            <CardTitle className="text-sm font-medium">
              {toolCall.name}
            </CardTitle>
          </div>
          <StatusIcon
            className={cn("h-4 w-4", color, animate && "animate-spin")}
          />
        </div>
      </CardHeader>
      <CardContent className="py-2 px-3 space-y-2">
        {/* Arguments */}
        <div className="group relative">
          <div className="flex items-center justify-between mb-1">
            <p className="text-xs text-muted-foreground">Arguments:</p>
            <CopyButton
              text={argsText}
              className="opacity-0 group-hover:opacity-100"
            />
          </div>
          <pre className="text-xs bg-background p-2 rounded overflow-x-auto">
            {argsText}
          </pre>
        </div>

        {/* Result */}
        {toolCall.result !== undefined && (
          <div className="group relative">
            <div className="flex items-center justify-between mb-1">
              <p className="text-xs text-muted-foreground">Result:</p>
              {resultText && (
                <CopyButton
                  text={resultText}
                  className="opacity-0 group-hover:opacity-100"
                />
              )}
            </div>

            {/* Render content parts if structured, otherwise show as text */}
            {isToolContentArray(toolCall.result) ? (
              <div className="space-y-2">
                {toolCall.result.map((part, index) => {
                  if (part.type === "text") {
                    return (
                      <pre
                        key={index}
                        className="text-xs bg-background p-2 rounded overflow-x-auto"
                      >
                        {part.text}
                      </pre>
                    );
                  } else if (part.type === "image") {
                    return (
                      <div key={index} className="relative">
                        <Image
                          src={`data:${part.media_type};base64,${part.data}`}
                          alt="Generated image"
                          width={512}
                          height={512}
                          className="rounded-lg max-w-full h-auto"
                          unoptimized
                        />
                      </div>
                    );
                  }
                  return null;
                })}
              </div>
            ) : (
              <pre className="text-xs bg-background p-2 rounded overflow-x-auto max-h-48 overflow-y-auto">
                {resultText}
              </pre>
            )}
          </div>
        )}
      </CardContent>
    </Card>
  );
}
