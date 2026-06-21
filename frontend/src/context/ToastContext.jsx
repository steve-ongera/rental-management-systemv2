import { createContext, useCallback, useContext, useState } from "react";
import { FiCheckCircle, FiAlertTriangle, FiInfo, FiXCircle } from "react-icons/fi";

const ToastContext = createContext(null);

let idCounter = 0;

export function ToastProvider({ children }) {
  const [toasts, setToasts] = useState([]);

  const removeToast = useCallback((id) => {
    setToasts((prev) => prev.filter((t) => t.id !== id));
  }, []);

  const showToast = useCallback(
    (message, type = "info", duration = 4000) => {
      const id = ++idCounter;
      setToasts((prev) => [...prev, { id, message, type }]);
      if (duration) {
        setTimeout(() => removeToast(id), duration);
      }
    },
    [removeToast]
  );

  const toast = {
    success: (msg, d) => showToast(msg, "success", d),
    error: (msg, d) => showToast(msg, "error", d),
    warn: (msg, d) => showToast(msg, "warn", d),
    info: (msg, d) => showToast(msg, "info", d),
  };

  const icons = {
    success: <FiCheckCircle />,
    error: <FiXCircle />,
    warn: <FiAlertTriangle />,
    info: <FiInfo />,
  };

  return (
    <ToastContext.Provider value={toast}>
      {children}
      <div className="toast-stack">
        {toasts.map((t) => (
          <div key={t.id} className={`toast ${t.type}`} onClick={() => removeToast(t.id)}>
            {icons[t.type]}
            <span>{t.message}</span>
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  );
}

export function useToast() {
  const ctx = useContext(ToastContext);
  if (!ctx) throw new Error("useToast must be used within ToastProvider");
  return ctx;
}