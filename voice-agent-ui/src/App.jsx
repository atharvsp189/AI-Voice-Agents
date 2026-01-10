// src/App.jsx
import { useState, useRef, useEffect } from 'react';
import { Mic, Square, Plus, Globe, MoreHorizontal } from 'lucide-react';
import './App.css';

function App() {
  const [isRecording, setIsRecording] = useState(false);
  const [transcripts, setTranscripts] = useState([]);
  const [connectionStatus, setConnectionStatus] = useState("Ready");
  
  // Refs to keep track of socket and recorder without triggering re-renders
  const socketRef = useRef(null);
  const mediaRecorderRef = useRef(null);
  const chatContainerRef = useRef(null);

  // Auto-scroll to bottom when new transcripts arrive
  useEffect(() => {
    if (chatContainerRef.current) {
      chatContainerRef.current.scrollTop = chatContainerRef.current.scrollHeight;
    }
  }, [transcripts]);

  const startRecording = async () => {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      
      // 1. Connect to Backend
      setConnectionStatus("Connecting...");
      socketRef.current = new WebSocket("ws://localhost:8000/listen");

      socketRef.current.onopen = () => {
        setConnectionStatus("Connected");
        setIsRecording(true);
        
        // 2. Start MediaRecorder
        const mediaRecorder = new MediaRecorder(stream, { mimeType: 'audio/webm' });
        mediaRecorderRef.current = mediaRecorder;

        mediaRecorder.addEventListener('dataavailable', (event) => {
          if (event.data.size > 0 && socketRef.current?.readyState === WebSocket.OPEN) {
            socketRef.current.send(event.data);
          }
        });

        mediaRecorder.start(250); // Send chunk every 250ms
      };

      socketRef.current.onmessage = (message) => {
        const data = JSON.parse(message.data);
        if (data.type === 'transcript') {
          setTranscripts(prev => {
            // Logic to update the last message if it's interim, or add new if final
            const lastMsg = prev[prev.length - 1];
            if (lastMsg && !lastMsg.isFinal) {
              // Replace interim message
              return [...prev.slice(0, -1), { text: data.text, isFinal: data.is_final }];
            } else {
              // Add new message
              return [...prev, { text: data.text, isFinal: data.is_final }];
            }
          });
        }
      };

      socketRef.current.onclose = () => {
        stopCleanup();
      };

      socketRef.current.onerror = () => {
        setConnectionStatus("Error");
        stopCleanup();
      };

    } catch (err) {
      console.error(err);
      setConnectionStatus("Microphone Error");
    }
  };

  const stopRecording = () => {
    if (mediaRecorderRef.current && mediaRecorderRef.current.state !== 'inactive') {
      mediaRecorderRef.current.stop();
      mediaRecorderRef.current.stream.getTracks().forEach(track => track.stop());
    }
    if (socketRef.current) {
      socketRef.current.close();
    }
    stopCleanup();
  };

  const stopCleanup = () => {
    setIsRecording(false);
    setConnectionStatus("Ready");
    socketRef.current = null;
    mediaRecorderRef.current = null;
  };

  const handleToggle = () => {
    if (isRecording) stopRecording();
    else startRecording();
  };

  return (
    <div className="app-container">
      {/* HEADER */}
      <header className="top-bar">
        <div className="menu-icon">
           <span className="brand">VoiceAI</span>
        </div>
        <div className="user-icon">AD</div>
      </header>

      {/* MAIN CONTENT AREA */}
      <main className="main-content" ref={chatContainerRef}>
        {transcripts.length === 0 ? (
          <div className="empty-state">
            <div className="logo-placeholder">🎙️</div>
            <h1>How can I help you today?</h1>
          </div>
        ) : (
          <div className="transcript-list">
            {transcripts.map((t, i) => (
              <div key={i} className={`message ${t.isFinal ? 'final' : 'interim'}`}>
                {t.text}
              </div>
            ))}
          </div>
        )}
      </main>

      {/* FLOATING INPUT BAR */}
      <div className="input-area-wrapper">
        <div className="input-bar">
          <button className="icon-btn secondary">
            <Plus size={24} />
          </button>

          <div className="text-input-placeholder">
            {connectionStatus === "Ready" ? "Start speaking..." : connectionStatus}
          </div>

          <div className="right-actions">
            <button className={`icon-btn main-action ${isRecording ? 'active' : ''}`} onClick={handleToggle}>
              {isRecording ? <Square size={20} fill="currentColor" /> : <Mic size={24} />}
            </button>
          </div>
        </div>
        
        <div className="footer-text">
          AI Voice Assistant • Powered by Deepgram & FastAPI
        </div>
      </div>
    </div>
  );
}

export default App;