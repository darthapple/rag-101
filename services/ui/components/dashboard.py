"""
Dashboard Component

System monitoring dashboard with real-time metrics visualization.
Displays system health, performance metrics, and activity monitoring.
"""

import streamlit as st
import plotly.graph_objects as go
import plotly.express as px
import pandas as pd
import requests
import logging
from typing import Dict, Any, List
from datetime import datetime, timedelta
import time


class Dashboard:
    """System monitoring dashboard component"""
    
    def __init__(self, config: Dict[str, Any]):
        """Initialize dashboard component"""
        self.config = config
        self.api_base_url = config['api_base_url']
        self.logger = logging.getLogger("ui.dashboard")
        
        # Initialize metrics storage
        if 'dashboard_metrics' not in st.session_state:
            st.session_state.dashboard_metrics = {
                'timestamps': [],
                'response_times': [],
                'active_sessions': [],
                'questions_asked': [],
                'documents_processed': []
            }
    
    def render(self):
        """Render the dashboard interface"""
        # System overview cards
        self._render_overview_cards()
        
        st.divider()
        
        # Performance charts
        col1, col2 = st.columns(2)
        
        with col1:
            self._render_response_time_chart()
        
        with col2:
            self._render_activity_chart()
        
        st.divider()
        
        # System health and logs
        col1, col2 = st.columns(2)
        
        with col1:
            self._render_system_health()
        
        with col2:
            self._render_recent_activity()
        
        # Auto-refresh logic
        self._handle_auto_refresh()
    
    def _render_overview_cards(self):
        """Render system overview metric cards"""
        st.subheader("📊 System Overview")
        
        # Fetch current metrics
        metrics = self._fetch_system_metrics()
        
        col1, col2, col3, col4 = st.columns(4)
        
        with col1:
            sessions_count = metrics.get('active_sessions', 0)
            sessions_delta = self._calculate_delta('active_sessions', sessions_count)
            st.metric(
                "Active Sessions",
                sessions_count,
                delta=sessions_delta,
                help="Number of currently active user sessions"
            )
        
        with col2:
            documents_count = metrics.get('documents_processed', 0)
            docs_delta = self._calculate_delta('documents_processed', documents_count)
            st.metric(
                "Documents Processed",
                documents_count,
                delta=docs_delta,
                help="Total number of documents processed successfully"
            )
        
        with col3:
            questions_count = metrics.get('questions_asked', 0)
            questions_delta = self._calculate_delta('questions_asked', questions_count)
            st.metric(
                "Questions Asked",
                questions_count,
                delta=questions_delta,
                help="Total number of questions submitted"
            )
        
        with col4:
            avg_response_time = metrics.get('avg_response_time', 0)
            response_delta = self._calculate_delta('avg_response_time', avg_response_time)
            st.metric(
                "Avg Response Time",
                f"{avg_response_time:.1f}s",
                delta=f"{response_delta:.1f}s" if response_delta else None,
                help="Average question response time"
            )
    
    def _render_response_time_chart(self):
        """Render response time trend chart"""
        st.subheader("⏱️ Response Time Trend")
        
        if not st.session_state.dashboard_metrics['timestamps']:
            st.info("No data available yet. Metrics will appear as the system is used.")
            return
        
        # Create DataFrame from metrics
        df = pd.DataFrame({
            'timestamp': st.session_state.dashboard_metrics['timestamps'],
            'response_time': st.session_state.dashboard_metrics['response_times']
        })
        
        # Create line chart
        fig = px.line(
            df,
            x='timestamp',
            y='response_time',
            title='Response Time Over Time',
            labels={'response_time': 'Response Time (seconds)', 'timestamp': 'Time'}
        )
        
        fig.update_layout(
            height=300,
            showlegend=False,
            xaxis_title="Time",
            yaxis_title="Response Time (s)"
        )
        
        st.plotly_chart(fig, use_container_width=True)
    
    def _render_activity_chart(self):
        """Render system activity chart"""
        st.subheader("📈 System Activity")
        
        if not st.session_state.dashboard_metrics['timestamps']:
            st.info("No activity data available yet.")
            return
        
        # Create DataFrame
        df = pd.DataFrame({
            'timestamp': st.session_state.dashboard_metrics['timestamps'],
            'sessions': st.session_state.dashboard_metrics['active_sessions'],
            'questions': st.session_state.dashboard_metrics['questions_asked']
        })
        
        # Create multi-line chart
        fig = go.Figure()
        
        fig.add_trace(go.Scatter(
            x=df['timestamp'],
            y=df['sessions'],
            mode='lines+markers',
            name='Active Sessions',
            line=dict(color='blue')
        ))
        
        fig.add_trace(go.Scatter(
            x=df['timestamp'],
            y=df['questions'],
            mode='lines+markers',
            name='Questions Asked',
            line=dict(color='green'),
            yaxis='y2'
        ))
        
        fig.update_layout(
            title='System Activity Over Time',
            height=300,
            xaxis_title='Time',
            yaxis=dict(
                title='Active Sessions',
                side='left'
            ),
            yaxis2=dict(
                title='Questions Asked',
                side='right',
                overlaying='y'
            )
        )
        
        st.plotly_chart(fig, use_container_width=True)
    
    def _render_system_health(self):
        """Render system health status"""
        st.subheader("🏥 System Health")
        
        # Fetch health data
        health_data = self._fetch_health_status()
        
        # API Service Health
        api_status = health_data.get('api', {})
        api_healthy = api_status.get('status') == 'healthy'
        
        st.markdown(f"""
        **API Service**
        <span style="color: {'green' if api_healthy else 'red'}">
        {'🟢 Healthy' if api_healthy else '🔴 Unhealthy'}
        </span>
        """, unsafe_allow_html=True)
        
        if api_status.get('response_time'):
            st.caption(f"Response time: {api_status['response_time']:.3f}s")
        
        # NATS Status
        nats_status = health_data.get('nats', {})
        nats_healthy = nats_status.get('connected', False)
        
        st.markdown(f"""
        **NATS Messaging**
        <span style="color: {'green' if nats_healthy else 'red'}">
        {'🟢 Connected' if nats_healthy else '🔴 Disconnected'}
        </span>
        """, unsafe_allow_html=True)
        
        # WebSocket Status
        ws_status = health_data.get('websocket', {})
        ws_connections = ws_status.get('active_connections', 0)
        
        st.markdown(f"""
        **WebSocket Connections**
        <span style="color: {'green' if ws_connections > 0 else 'orange'}">
        {ws_connections} active
        </span>
        """, unsafe_allow_html=True)
        
        # System uptime (placeholder)
        uptime = health_data.get('uptime', 'Unknown')
        st.markdown(f"**System Uptime:** {uptime}")
    
    def _render_recent_activity(self):
        """Render recent system activity log"""
        st.subheader("📝 Recent Activity")
        
        # Placeholder activity log (would come from actual logging system)
        activities = [
            {"time": "14:30:25", "event": "New session created", "user": "user_123"},
            {"time": "14:29:52", "event": "Document processed", "doc": "diabetes-protocol.pdf"},
            {"time": "14:28:41", "event": "Question answered", "response_time": "3.2s"},
            {"time": "14:27:15", "event": "WebSocket connected", "session": "sess_456"},
            {"time": "14:25:03", "event": "Rate limit triggered", "ip": "192.168.1.100"},
        ]
        
        for activity in activities:
            time_str = activity["time"]
            event = activity["event"]
            
            if "session created" in event:
                st.markdown(f"🔵 `{time_str}` - {event}")
            elif "processed" in event:
                st.markdown(f"🟢 `{time_str}` - {event}")
            elif "answered" in event:
                st.markdown(f"💬 `{time_str}` - {event} ({activity.get('response_time', 'N/A')})")
            elif "connected" in event:
                st.markdown(f"🔌 `{time_str}` - {event}")
            elif "rate limit" in event:
                st.markdown(f"⚠️ `{time_str}` - {event}")
            else:
                st.markdown(f"📝 `{time_str}` - {event}")
        
        # Refresh button
        if st.button("🔄 Refresh Activity", type="secondary", key="refresh_activity"):
            st.rerun()
    
    def _fetch_system_metrics(self) -> Dict[str, Any]:
        """Fetch system metrics from API services"""
        metrics = {
            'active_sessions': 0,
            'documents_processed': 0,
            'questions_asked': 0,
            'avg_response_time': 0.0
        }
        
        try:
            # Fetch from API service
            response = requests.get(
                f"{self.api_base_url}/health",
                timeout=5
            )
            
            if response.status_code == 200:
                health_data = response.json()
                
                # Extract metrics from health response
                if 'stats' in health_data:
                    stats = health_data['stats']
                    metrics.update({
                        'active_sessions': stats.get('active_sessions', 0),
                        'documents_processed': stats.get('total_documents', 0),
                        'questions_asked': stats.get('total_questions', 0),
                        'avg_response_time': stats.get('avg_response_time', 0.0)
                    })
        
        except Exception as e:
            self.logger.error(f"Failed to fetch system metrics: {e}")
        
        return metrics
    
    def _fetch_health_status(self) -> Dict[str, Any]:
        """Fetch detailed health status"""
        health_data = {
            'api': {'status': 'unknown'},
            'nats': {'connected': False},
            'websocket': {'active_connections': 0},
            'uptime': 'Unknown'
        }
        
        try:
            # Check API health
            start_time = time.time()
            response = requests.get(
                f"{self.api_base_url}/health",
                timeout=5
            )
            response_time = time.time() - start_time
            
            if response.status_code == 200:
                health_data['api'] = {
                    'status': 'healthy',
                    'response_time': response_time
                }
                
                # Extract additional health info
                api_health = response.json()
                health_data.update(api_health)
            else:
                health_data['api']['status'] = 'unhealthy'
        
        except Exception as e:
            self.logger.error(f"Health check failed: {e}")
            health_data['api']['status'] = 'error'
        
        return health_data
    
    def _calculate_delta(self, metric_name: str, current_value: float) -> float:
        """Calculate delta for metric display"""
        if metric_name not in st.session_state.dashboard_metrics:
            return 0
        
        history = st.session_state.dashboard_metrics.get(metric_name, [])
        if len(history) < 2:
            return 0
        
        previous_value = history[-2] if len(history) > 1 else 0
        return current_value - previous_value
    
    def _handle_auto_refresh(self):
        """Handle dashboard auto-refresh"""
        # Store current metrics for trend analysis
        current_time = datetime.now()
        metrics = self._fetch_system_metrics()
        
        # Update metrics history
        max_history = 50  # Keep last 50 data points
        
        for key in ['timestamps', 'active_sessions', 'questions_asked', 'documents_processed', 'response_times']:
            if key not in st.session_state.dashboard_metrics:
                st.session_state.dashboard_metrics[key] = []
        
        # Add current data point
        st.session_state.dashboard_metrics['timestamps'].append(current_time)
        st.session_state.dashboard_metrics['active_sessions'].append(metrics['active_sessions'])
        st.session_state.dashboard_metrics['questions_asked'].append(metrics['questions_asked'])
        st.session_state.dashboard_metrics['documents_processed'].append(metrics['documents_processed'])
        st.session_state.dashboard_metrics['response_times'].append(metrics['avg_response_time'])
        
        # Trim history to max length
        for key, values in st.session_state.dashboard_metrics.items():
            if len(values) > max_history:
                st.session_state.dashboard_metrics[key] = values[-max_history:]


def format_uptime(seconds: float) -> str:
    """Format uptime in human-readable format"""
    if seconds < 60:
        return f"{seconds:.0f}s"
    elif seconds < 3600:
        return f"{seconds/60:.0f}m"
    elif seconds < 86400:
        return f"{seconds/3600:.1f}h"
    else:
        return f"{seconds/86400:.1f}d"