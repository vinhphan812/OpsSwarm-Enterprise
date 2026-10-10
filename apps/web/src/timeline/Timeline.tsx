import { AgentEvent } from "../events/types";
import "./Timeline.css";

interface Props {
  events: AgentEvent[];
}

export function Timeline({ events }: Props) {
  return (
    <div className="agent-timeline">
      {events.map((event) => (
        <div key={event.eventId} className="agent-event">
          <div className="event-header">
            <span>{event.eventId}</span>
            <span>{event.overallStatus}</span>
          </div>
          {event.stages.map((stage, idx) => (
            <div key={idx} className="stage-row">
              <div className={`stage-status status-${stage.status}`} />
              <div>
                <div style={{ fontWeight: 'bold' }}>{stage.stage}</div>
                <div style={{ fontSize: '0.8rem', color: '#94a3b8' }}>{stage.summary}</div>
                {stage.failureReason && (
                  <div className="failure-reason">Error: {stage.failureReason}</div>
                )}
              </div>
            </div>
          ))}
        </div>
      ))}
    </div>
  );
}
