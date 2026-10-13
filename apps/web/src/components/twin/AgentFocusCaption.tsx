import { AnimatePresence, motion } from "framer-motion";
import { useTranslation } from "react-i18next";
import { ActivityIcon } from "@/components/icons";
import { useUiStore } from "@/state/ui.store";

/**
 * Why the camera moved, while the selection is the agent's (`focusEntity`): the activity
 * entry's summary at the bottom of the 3D view. Gone once the user selects something else.
 */
export function AgentFocusCaption() {
  const { t } = useTranslation();
  const reason = useUiStore((state) => state.focusReason);
  const seq = useUiStore((state) => state.focusSeq);

  return (
    <AnimatePresence>
      {reason ? (
        <motion.div
          key={seq}
          className="agent-focus-caption"
          role="status"
          initial={{ opacity: 0, y: 8 }}
          animate={{ opacity: 1, y: 0 }}
          exit={{ opacity: 0 }}
          transition={{ duration: 0.2, ease: "easeOut" }}
        >
          <span className="agent-focus-caption-source">
            <ActivityIcon className="h-3.5 w-3.5 shrink-0" />
            {t("agentFocus.source")}
          </span>
          <span>{reason}</span>
        </motion.div>
      ) : null}
    </AnimatePresence>
  );
}
