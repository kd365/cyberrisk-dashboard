import React, { useState, useRef, useEffect } from 'react';

/**
 * LexChatbot Component
 * Provides a chat interface for Amazon Lex V2 bot integration
 * Helps users navigate and understand dashboard data
 */

const LexChatbot = () => {
  const [messages, setMessages] = useState([
    {
      type: 'bot',
      content: `Welcome to the CyberRisk Dashboard Assistant! I can help you with:

- List available companies
- Get information about specific companies
- Check sentiment analysis results
- View forecast predictions
- Explain dashboard features
- Add new companies to track
- Remove companies from the dashboard

Just type your question below or try "What companies are available?" or "Add a new company"!`
    }
  ]);
  const [inputText, setInputText] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [sessionId, setSessionId] = useState(null);
  const messagesEndRef = useRef(null);

  // Generate session ID on mount
  useEffect(() => {
    setSessionId(`session-${Date.now()}-${Math.random().toString(36).substr(2, 9)}`);
  }, []);

  // Auto-scroll to bottom of messages
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  const sendMessage = async () => {
    if (!inputText.trim() || isLoading) return;

    const userMessage = inputText.trim();
    setInputText('');

    // Add user message to chat
    setMessages(prev => [...prev, { type: 'user', content: userMessage }]);
    setIsLoading(true);

    try {
      const response = await fetch('/api/lex/message', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          message: userMessage,
          sessionId: sessionId
        })
      });

      if (!response.ok) {
        throw new Error('Failed to get response from assistant');
      }

      const data = await response.json();

      // Add bot response to chat
      setMessages(prev => [...prev, {
        type: 'bot',
        content: data.message || "I'm sorry, I couldn't process that request."
      }]);

    } catch (error) {
      console.error('Error sending message to Lex:', error);
      setMessages(prev => [...prev, {
        type: 'bot',
        content: "I'm having trouble connecting right now. Please try again in a moment."
      }]);
    } finally {
      setIsLoading(false);
    }
  };

  const handleKeyPress = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      sendMessage();
    }
  };

  const quickActions = [
    { label: 'List Companies', message: 'What companies are available?' },
    { label: 'Add Company', message: 'I want to add a new company' },
    { label: 'Dashboard Features', message: 'What features does the dashboard have?' },
    { label: 'Help', message: 'help' }
  ];

  const styles = {
    container: {
      display: 'flex',
      flexDirection: 'column',
      height: '600px',
      maxHeight: '70vh',
      background: '#f8fafc',
      borderRadius: '12px',
      overflow: 'hidden',
      border: '1px solid #e2e8f0'
    },
    header: {
      background: '#1c2434',
      color: '#fff',
      padding: '16px 20px',
      display: 'flex',
      alignItems: 'center',
      gap: '12px'
    },
    headerIcon: {
      width: '40px',
      height: '40px',
      background: '#3c50e0',
      borderRadius: '10px',
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'center'
    },
    headerText: {
      flex: 1
    },
    headerTitle: {
      fontSize: '16px',
      fontWeight: '600',
      marginBottom: '2px'
    },
    headerSubtitle: {
      fontSize: '12px',
      color: '#8a99af'
    },
    statusDot: {
      width: '8px',
      height: '8px',
      borderRadius: '50%',
      background: '#10b981',
      marginRight: '6px',
      display: 'inline-block'
    },
    messagesContainer: {
      flex: 1,
      overflowY: 'auto',
      padding: '20px'
    },
    message: (isUser) => ({
      display: 'flex',
      justifyContent: isUser ? 'flex-end' : 'flex-start',
      marginBottom: '16px'
    }),
    messageBubble: (isUser) => ({
      maxWidth: '80%',
      padding: '12px 16px',
      borderRadius: isUser ? '16px 16px 4px 16px' : '16px 16px 16px 4px',
      background: isUser ? '#3c50e0' : '#fff',
      color: isUser ? '#fff' : '#1e293b',
      fontSize: '14px',
      lineHeight: '1.5',
      boxShadow: isUser ? 'none' : '0 1px 3px rgba(0,0,0,0.08)',
      whiteSpace: 'pre-wrap'
    }),
    quickActionsContainer: {
      padding: '12px 20px',
      background: '#fff',
      borderBottom: '1px solid #e2e8f0',
      display: 'flex',
      gap: '8px',
      flexWrap: 'wrap'
    },
    quickAction: {
      padding: '6px 12px',
      background: '#f1f5f9',
      border: '1px solid #e2e8f0',
      borderRadius: '16px',
      fontSize: '12px',
      color: '#475569',
      cursor: 'pointer',
      transition: 'all 150ms ease'
    },
    inputContainer: {
      display: 'flex',
      padding: '16px 20px',
      background: '#fff',
      borderTop: '1px solid #e2e8f0',
      gap: '12px'
    },
    input: {
      flex: 1,
      padding: '12px 16px',
      border: '1px solid #e2e8f0',
      borderRadius: '24px',
      fontSize: '14px',
      outline: 'none',
      transition: 'border-color 150ms ease'
    },
    sendButton: {
      width: '44px',
      height: '44px',
      borderRadius: '50%',
      background: '#3c50e0',
      border: 'none',
      color: '#fff',
      cursor: 'pointer',
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'center',
      transition: 'background 150ms ease'
    },
    loadingDots: {
      display: 'flex',
      gap: '4px',
      padding: '12px 16px'
    },
    dot: {
      width: '8px',
      height: '8px',
      borderRadius: '50%',
      background: '#94a3b8',
      animation: 'bounce 1.4s infinite ease-in-out both'
    },
    infoBox: {
      margin: '16px 20px',
      padding: '12px 16px',
      background: '#eff6ff',
      border: '1px solid #bfdbfe',
      borderRadius: '8px',
      fontSize: '13px',
      color: '#1e40af'
    }
  };

  // Add keyframes for loading animation
  useEffect(() => {
    const style = document.createElement('style');
    style.textContent = `
      @keyframes bounce {
        0%, 80%, 100% { transform: scale(0); }
        40% { transform: scale(1); }
      }
    `;
    document.head.appendChild(style);
    return () => document.head.removeChild(style);
  }, []);

  return (
    <div style={styles.container}>
      {/* Header */}
      <div style={styles.header}>
        <div style={styles.headerIcon}>
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" />
          </svg>
        </div>
        <div style={styles.headerText}>
          <div style={styles.headerTitle}>AI Assistant</div>
          <div style={styles.headerSubtitle}>
            <span style={styles.statusDot}></span>
            Powered by Amazon Lex
          </div>
        </div>
      </div>

      {/* Quick Actions */}
      <div style={styles.quickActionsContainer}>
        {quickActions.map((action, index) => (
          <button
            key={index}
            style={styles.quickAction}
            onClick={() => {
              setInputText(action.message);
              setTimeout(sendMessage, 100);
            }}
            onMouseEnter={(e) => {
              e.target.style.background = '#e2e8f0';
              e.target.style.borderColor = '#cbd5e1';
            }}
            onMouseLeave={(e) => {
              e.target.style.background = '#f1f5f9';
              e.target.style.borderColor = '#e2e8f0';
            }}
          >
            {action.label}
          </button>
        ))}
      </div>

      {/* Messages */}
      <div style={styles.messagesContainer}>
        {messages.map((msg, index) => (
          <div key={index} style={styles.message(msg.type === 'user')}>
            <div style={styles.messageBubble(msg.type === 'user')}>
              {msg.content}
            </div>
          </div>
        ))}

        {isLoading && (
          <div style={styles.message(false)}>
            <div style={{ ...styles.messageBubble(false), background: '#f1f5f9' }}>
              <div style={styles.loadingDots}>
                <div style={{ ...styles.dot, animationDelay: '-0.32s' }}></div>
                <div style={{ ...styles.dot, animationDelay: '-0.16s' }}></div>
                <div style={styles.dot}></div>
              </div>
            </div>
          </div>
        )}

        <div ref={messagesEndRef} />
      </div>

      {/* Info Box */}
      <div style={styles.infoBox}>
        This AI assistant uses AWS Comprehend for understanding and Amazon Lex for conversation management.
        Ask about companies, sentiment analysis, or forecasts!
      </div>

      {/* Input */}
      <div style={styles.inputContainer}>
        <input
          type="text"
          value={inputText}
          onChange={(e) => setInputText(e.target.value)}
          onKeyPress={handleKeyPress}
          placeholder="Ask me anything about the dashboard..."
          style={styles.input}
          disabled={isLoading}
          onFocus={(e) => e.target.style.borderColor = '#3c50e0'}
          onBlur={(e) => e.target.style.borderColor = '#e2e8f0'}
        />
        <button
          onClick={sendMessage}
          disabled={isLoading || !inputText.trim()}
          style={{
            ...styles.sendButton,
            opacity: isLoading || !inputText.trim() ? 0.5 : 1,
            cursor: isLoading || !inputText.trim() ? 'not-allowed' : 'pointer'
          }}
          onMouseEnter={(e) => {
            if (!isLoading && inputText.trim()) {
              e.target.style.background = '#2d3eb8';
            }
          }}
          onMouseLeave={(e) => {
            e.target.style.background = '#3c50e0';
          }}
        >
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <line x1="22" y1="2" x2="11" y2="13" />
            <polygon points="22 2 15 22 11 13 2 9 22 2" />
          </svg>
        </button>
      </div>
    </div>
  );
};

export default LexChatbot;
