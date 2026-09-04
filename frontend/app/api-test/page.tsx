"use client";

import { useEffect, useState } from "react";

type HealthResponse = {
  status: string;
  service: string;
  database: string;
  environment: string;
};

export default function ApiTestPage() {
  const [data, setData] = useState<HealthResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetch("http://localhost:8000/health")
      .then(async (response) => {
        if (!response.ok) {
          throw new Error("Backend request failed");
        }

        return response.json();
      })
      .then(setData)
      .catch((err) => {
        setError(err.message);
      });
  }, []);

  return (
    <main className="min-h-screen flex items-center justify-center">
      <div className="w-full max-w-xl rounded-xl border p-8">
        <h1 className="text-2xl font-bold">
          MerchantOS System Check
        </h1>

        {error && (
          <div className="mt-6 rounded-lg border p-4">
            Backend error: {error}
          </div>
        )}

        {data && (
          <pre className="mt-6 rounded-lg border p-4 text-sm">
            {JSON.stringify(data, null, 2)}
          </pre>
        )}

        {!data && !error && (
          <p className="mt-6 text-sm">
            Connecting to backend...
          </p>
        )}
      </div>
    </main>
  );
}