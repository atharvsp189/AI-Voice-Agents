// src/App.jsx
import { useState, useRef, useEffect } from 'react';
import { IoMic, IoSend, IoStop } from 'react-icons/io5'; 
import './App.css';

function App() {
  const [isRecording, setIsRecording] = useState(false);
  const [transcripts, setTranscripts] = useState([]); 
  const [inputText, setInputText] = useState("");     
  const [connectionStatus, setConnectionStatus] = useState("Ready");
  
  const socketRef = useRef(null);
  const mediaRecorderRef = useRef(null);
  const chatContainerRef = useRef(null);
  const textareaRef = useRef(null); // Ref for auto-resizing
  const confirmedTextRef = useRef(""); 

  // Auto-scroll chat to bottom
  useEffect(() => {
    if (chatContainerRef.current) {
      chatContainerRef.current.scrollTop = chatContainerRef.current.scrollHeight;
    }
  }, [transcripts]);

  // Auto-resize Textarea
  useEffect(() => {
    if (textareaRef.current) {
      // Reset height to auto to correctly calculate new scrollHeight (allows shrinking)
      textareaRef.current.style.height = "auto";
      // Set height to scrollHeight to fit content
      textareaRef.current.style.height = `${textareaRef.current.scrollHeight}px`;
    }
  }, [inputText]);

  const startRecording = async () => {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      setConnectionStatus("Connecting...");
      socketRef.current = new WebSocket("ws://localhost:8000/listen");

      socketRef.current.onopen = () => {
        setConnectionStatus("Listening...");
        setIsRecording(true);
        confirmedTextRef.current = inputText; 

        const mediaRecorder = new MediaRecorder(stream, { mimeType: 'audio/webm' });
        mediaRecorderRef.current = mediaRecorder;

        mediaRecorder.addEventListener('dataavailable', (event) => {
          if (event.data.size > 0 && socketRef.current?.readyState === WebSocket.OPEN) {
            socketRef.current.send(event.data);
          }
        });

        mediaRecorder.start(250);
      };

      socketRef.current.onmessage = (message) => {
        const data = JSON.parse(message.data);
        if (data.type === 'transcript') {
          const transcript = data.text;
          const isFinal = data.is_final;
          if (isFinal) {
            confirmedTextRef.current += (confirmedTextRef.current ? " " : "") + transcript;
            setInputText(confirmedTextRef.current);
          } else {
            setInputText((confirmedTextRef.current ? confirmedTextRef.current + " " : "") + transcript);
          }
        }
      };

      socketRef.current.onerror = () => {
        setConnectionStatus("Error");
        stopCleanup();
      };

      socketRef.current.onclose = () => {
        if (isRecording) stopCleanup();
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
    confirmedTextRef.current = inputText; 
  };

  const handleToggleRecord = () => {
    if (isRecording) stopRecording();
    else startRecording();
  };

  const handleSend = () => {
    if (!inputText.trim()) return;

    setTranscripts(prev => [
      ...prev, 
      { text: inputText, sender: 'user', isFinal: true }
    ]);

    setInputText("");
    confirmedTextRef.current = "";

    setTimeout(() => {
      setTranscripts(prev => [
        ...prev,
        { text: "Transcription done", sender: 'agent', isFinal: true }
      ]);
    }, 600);
  };

  // Handle Enter Key
  const handleKeyDown = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault(); // Prevent new line
      handleSend();
    }
  };

  return (
    <div className="app-container">
      {/* HEADER */}
      <header className="top-bar">
        <div className="brand">VoiceAI</div>
        <div className="user-icon">AP</div>
      </header>

      {/* CHAT AREA */}
      <main className="main-content" ref={chatContainerRef}>
        {transcripts.length === 0 ? (
          <div className="empty-state">
            <div className="logo-placeholder">🎙️</div>
            <h1>How can I help you today?</h1>
          </div>
        ) : (
          <div className="transcript-list">
            {transcripts.map((t, i) => (
              <div key={i} className={`message ${t.sender}`}>
                {t.text}
              </div>
            ))}
          </div>
        )}
      </main>

      {/* INPUT BAR */}
      <div className="input-area-wrapper">
        <div className="input-bar">
          
          <textarea 
            ref={textareaRef}
            className="text-input"
            placeholder={isRecording ? "Listening..." : "Start speaking or type..."}
            value={inputText}
            onChange={(e) => {
              setInputText(e.target.value);
              confirmedTextRef.current = e.target.value; 
            }}
            onKeyDown={handleKeyDown}
            rows={1}
          />

          <div className="right-actions">
            
            {/* Mic / Stop Button */}
            <button 
              className={`icon-btn mic-action ${isRecording ? 'recording' : ''}`} 
              onClick={handleToggleRecord}
            >
              {isRecording ? <IoStop size={24} /> : <IoMic size={24} />}
            </button>

            {/* Send Button */}
            <button 
              className={`icon-btn send-action ${!inputText.trim() ? 'disabled' : ''}`}
              onClick={handleSend}
              disabled={!inputText.trim()} 
            >
              <IoSend size={24} />
            </button>

          </div>
        </div>
        
        <div className="footer-text">
          {connectionStatus === "Listening..." ? "🔴 Listening..." : "AI Voice Assistant"}
        </div>
      </div>
    </div>
  );
}

export default App;