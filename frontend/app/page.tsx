"use client";

import { useState, useRef, useEffect } from "react";
import { useDropzone } from "react-dropzone";
import axios from "axios";

type Message = {
  role: "user" | "assistant";
  content: string;
  sources?: string[];
};

interface ApiError {
  response?: {
    data?: {
      detail?: string;
    };
  };
  message?: string;
}

export default function Home() {
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [isUploading, setIsUploading] = useState(false);
  const [isAsking, setIsAsking] = useState(false);
  const [uploadStatus, setUploadStatus] = useState("");
  const chatEndRef = useRef<HTMLDivElement>(null);

  const API_BASE = "http://localhost:8000";

  // Auto-scroll to bottom when new messages arrive
  useEffect(() => {
    chatEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, isAsking]);

  const onDrop = async (acceptedFiles: File[]) => {
    const file = acceptedFiles[0];
    if (!file) return;

    setIsUploading(true);
    setUploadStatus(`Uploading ${file.name}...`);

    const formData = new FormData();
    formData.append("file", file);

    try {
      const res = await axios.post(`${API_BASE}/upload`, formData, {
        headers: { "Content-Type": "multipart/form-data" },
      });
      setUploadStatus(`✅ ${res.data.message}`);
      setTimeout(() => setUploadStatus(""), 3000);
    } catch (err: unknown) {
      const error = err as ApiError;
      setUploadStatus(
        `❌ Error: ${error.response?.data?.detail || error.message}`,
      );
    } finally {
      setIsUploading(false);
    }
  };

  const { getRootProps, getInputProps, isDragActive } = useDropzone({
    onDrop,
    accept: { "application/pdf": [".pdf"] },
    multiple: false,
  });

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!input.trim() || isAsking) return;

    const userMessage: Message = { role: "user", content: input };
    setMessages((prev) => [...prev, userMessage]);
    setInput("");
    setIsAsking(true);

    try {
      const res = await axios.post(`${API_BASE}/ask`, {
        question: input,
        top_k: 3,
      });

      const assistantMessage: Message = {
        role: "assistant",
        content: res.data.answer,
        sources: res.data.sources,
      };
      setMessages((prev) => [...prev, assistantMessage]);
    } catch (err: unknown) {
      const error = err as ApiError;
      setMessages((prev) => [
        ...prev,
        {
          role: "assistant" as const,
          content: `❌ Error: ${error.response?.data?.detail || error.message}`,
        },
      ]);
    } finally {
      setIsAsking(false);
    }
  };

  return (
    <main className="min-h-screen bg-gray-950 text-gray-100">
      <div className="max-w-4xl mx-auto p-6">
        {/* Header */}
        <h1 className="text-3xl font-bold mb-6 text-white">📄 Document Q&A</h1>

        {/* Upload area */}
        <div
          {...getRootProps()}
          className={`border-2 border-dashed rounded-xl p-8 mb-4 text-center cursor-pointer transition-all duration-200 ${
            isDragActive
              ? "border-blue-400 bg-blue-950/50 text-blue-300"
              : "border-gray-600 bg-gray-900 hover:border-gray-400 hover:bg-gray-800/50"
          }`}
        >
          <input {...getInputProps()} />
          {isUploading ? (
            <p className="text-yellow-400 animate-pulse">⏳ Uploading...</p>
          ) : (
            <p className="text-gray-400">
              📎 Drag & drop a PDF here, or click to select
            </p>
          )}
        </div>

        {uploadStatus && (
          <div className="mb-4 text-sm px-3 py-2 rounded-lg bg-gray-800 text-gray-200">
            {uploadStatus}
          </div>
        )}

        {/* Chat area */}
        <div className="border border-gray-700 rounded-xl h-125 overflow-y-auto p-4 mb-4 bg-gray-900">
          {messages.length === 0 && (
            <div className="flex items-center justify-center h-full">
              <p className="text-gray-500 text-center text-lg">
                Upload a PDF, then ask questions about its content.
              </p>
            </div>
          )}

          {messages.map((msg, idx) => (
            <div
              key={idx}
              className={`mb-4 flex ${
                msg.role === "user" ? "justify-end" : "justify-start"
              }`}
            >
              <div
                className={`max-w-[80%] px-4 py-3 rounded-2xl ${
                  msg.role === "user"
                    ? "bg-blue-600 text-white rounded-br-sm"
                    : "bg-gray-800 text-gray-100 border border-gray-700 rounded-bl-sm"
                }`}
              >
                <div
                  className={`font-semibold text-xs mb-1 ${
                    msg.role === "user" ? "text-blue-200" : "text-emerald-400"
                  }`}
                >
                  {msg.role === "user" ? "You" : "🤖 AI"}
                </div>
                <div className="whitespace-pre-wrap leading-relaxed">
                  {msg.content}
                </div>
                {msg.sources && msg.sources.length > 0 && (
                  <div className="text-xs text-gray-400 mt-2 pt-2 border-t border-gray-600">
                    📚 Sources: {msg.sources.join(", ")}
                  </div>
                )}
              </div>
            </div>
          ))}

          {isAsking && (
            <div className="flex justify-start mb-4">
              <div className="bg-gray-800 border border-gray-700 px-4 py-3 rounded-2xl rounded-bl-sm">
                <div className="flex items-center gap-2 text-emerald-400">
                  <div className="flex gap-1">
                    <span className="w-2 h-2 bg-emerald-400 rounded-full animate-bounce [animation-delay:0ms]"></span>
                    <span className="w-2 h-2 bg-emerald-400 rounded-full animate-bounce [animation-delay:150ms]"></span>
                    <span className="w-2 h-2 bg-emerald-400 rounded-full animate-bounce [animation-delay:300ms]"></span>
                  </div>
                  <span className="text-sm">Thinking...</span>
                </div>
              </div>
            </div>
          )}

          <div ref={chatEndRef} />
        </div>

        {/* Input form */}
        <form onSubmit={handleSubmit} className="flex gap-3">
          <input
            type="text"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder="Ask a question about your document..."
            className="flex-1 bg-gray-800 border border-gray-600 text-gray-100 placeholder-gray-500 px-4 py-3 rounded-xl focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent transition"
            disabled={isAsking}
          />
          <button
            type="submit"
            disabled={isAsking}
            className="bg-blue-600 hover:bg-blue-500 text-white px-6 py-3 rounded-xl font-medium transition disabled:bg-gray-700 disabled:text-gray-500 disabled:cursor-not-allowed"
          >
            Send
          </button>
        </form>
      </div>
    </main>
  );
}
