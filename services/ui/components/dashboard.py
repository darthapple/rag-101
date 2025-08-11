"""
Dashboard Component

System monitoring dashboard with real-time metrics visualization.
Displays system health, performance metrics, and NATS topic monitoring with activity indicators.
"""

import streamlit as st
import plotly.graph_objects as go
import plotly.express as px
import pandas as pd
import requests
import logging
import asyncio
import threading
from typing import Dict, Any, List, Optional
from datetime import datetime, timedelta
import time

# NATS imports
import nats
from nats.errors import ConnectionClosedError, TimeoutError


class Dashboard:
    """System monitoring dashboard component"""
    
    def __init__(self, config: Dict[str, Any]):
        """Initialize dashboard component"""
        self.config = config
        self.api_base_url = config['api_base_url']
        self.nats_url = config.get('nats_url', 'nats://localhost:4222')
        self.logger = logging.getLogger("ui.dashboard")
        
        # NATS connection
        self.nc: Optional[nats.NATS] = None
        self.js = None
        self.nats_connected = False
        
        # Initialize metrics storage
        if 'dashboard_metrics' not in st.session_state:
            st.session_state.dashboard_metrics = {
                'timestamps': [],
                'response_times': [],
                'active_sessions': [],
                'questions_asked': [],
                'documents_processed': []
            }
        
        # Initialize NATS metrics
        if 'nats_metrics' not in st.session_state:
            st.session_state.nats_metrics = {
                'topics': {},
                'last_activity': {},
                'message_rates': {},
                'last_updated': None
            }
    
    def render(self):
        """Render the dashboard interface"""
        # Initialize NATS connection if not connected
        if not self.nats_connected:
            self._initialize_nats_connection()
        
        # Initialize WebSocket integration for live updates
        self._initialize_websocket_integration()
        
        # System overview cards
        self._render_overview_cards()
        
        st.divider()
        
        # NATS topic monitoring section
        self._render_nats_topics_section()
        
        st.divider()
        
        # NATS visualization charts
        col1, col2 = st.columns(2)
        
        with col1:
            self._render_nats_message_rates_chart()
        
        with col2:
            self._render_nats_topic_activity_chart()
        
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
    
    def _render_nats_message_rates_chart(self):
        """Render NATS message rates chart with Plotly"""
        st.subheader("📈 NATS Message Rates")
        
        topics_data = st.session_state.nats_metrics.get('topics', {})
        if not topics_data:
            st.info("📊 No NATS topic data available yet.")
            return
        
        # Prepare data for bar chart
        topics = []
        message_counts = []
        bytes_counts = []
        
        for topic, stats in topics_data.items():
            topics.append(topic.replace('.', ' ').title())
            message_counts.append(stats.get('messages', 0))
            bytes_counts.append(stats.get('bytes', 0) / 1024)  # Convert to KB
        
        # Create dual-axis bar chart
        fig = go.Figure()
        
        # Messages bar
        fig.add_trace(go.Bar(
            x=topics,
            y=message_counts,
            name='Messages',
            marker_color='lightblue',
            yaxis='y',
            offsetgroup=1
        ))
        
        # Bytes bar (secondary axis)
        fig.add_trace(go.Bar(
            x=topics,
            y=bytes_counts,
            name='Bytes (KB)',
            marker_color='orange',
            yaxis='y2',
            offsetgroup=2
        ))
        
        # Update layout
        fig.update_layout(
            title='NATS Topic Message & Byte Counts',
            height=350,
            barmode='group',
            xaxis=dict(title='Topics'),
            yaxis=dict(
                title='Message Count',
                side='left'
            ),
            yaxis2=dict(
                title='Bytes (KB)',
                side='right',
                overlaying='y'
            ),
            legend=dict(
                orientation="h",
                yanchor="bottom",
                y=1.02,
                xanchor="right",
                x=1
            ),
            hovermode='x unified'
        )
        
        st.plotly_chart(fig, use_container_width=True)
    
    def _render_nats_topic_activity_chart(self):
        """Render NATS topic activity status pie chart"""
        st.subheader("📊 Topic Activity Status")
        
        topics_data = st.session_state.nats_metrics.get('topics', {})
        if not topics_data:
            st.info("📊 No NATS topic data available yet.")
            return
        
        # Count status distribution
        status_counts = {'Active': 0, 'Idle': 0, 'Error': 0}
        topic_details = []
        
        for topic, stats in topics_data.items():
            status = stats.get('status', 'unknown')
            if status == 'active':
                status_counts['Active'] += 1
            elif status == 'idle':
                status_counts['Idle'] += 1
            else:
                status_counts['Error'] += 1
            
            topic_details.append({
                'Topic': topic,
                'Status': status.title(),
                'Messages': stats.get('messages', 0),
                'Consumers': stats.get('consumers', 0)
            })
        
        # Create pie chart
        colors = ['#28a745', '#ffc107', '#dc3545']  # Green, Yellow, Red
        fig = go.Figure(data=[go.Pie(
            labels=list(status_counts.keys()),
            values=list(status_counts.values()),
            hole=0.4,
            marker_colors=colors,
            textinfo='label+percent',
            hovertemplate='<b>%{label}</b><br>Count: %{value}<br>Percentage: %{percent}<extra></extra>'
        )])
        
        fig.update_layout(
            title='NATS Topic Status Distribution',
            height=350,
            showlegend=True,
            legend=dict(
                orientation="v",
                yanchor="middle",
                y=0.5,
                xanchor="left",
                x=1.05
            )
        )
        
        st.plotly_chart(fig, use_container_width=True)
        
        # Show detailed table
        if topic_details:
            with st.expander("📋 Detailed Topic Information"):
                df = pd.DataFrame(topic_details)
                st.dataframe(df, use_container_width=True, hide_index=True)
    
    def _initialize_nats_connection(self):
        """Initialize NATS connection for monitoring"""
        if self.nats_connected:
            return
            
        try:
            # Start NATS connection in background thread
            def connect_nats():
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                loop.run_until_complete(self._connect_to_nats())
                loop.run_forever()
            
            thread = threading.Thread(target=connect_nats, daemon=True)
            thread.start()
            
            self.logger.info("NATS connection thread started")
            
        except Exception as e:
            self.logger.error(f"Failed to initialize NATS connection: {e}")
    
    async def _connect_to_nats(self):
        """Connect to NATS server"""
        try:
            self.nc = await nats.connect(
                servers=[self.nats_url],
                reconnect_time_wait=2,
                max_reconnect_attempts=5,
                connect_timeout=5,
                error_cb=self._nats_error_cb,
                disconnected_cb=self._nats_disconnected_cb,
                reconnected_cb=self._nats_reconnected_cb
            )
            
            # Initialize JetStream context
            self.js = self.nc.jetstream()
            self.nats_connected = True
            
            self.logger.info(f"Connected to NATS at {self.nats_url}")
            
            # Start monitoring task
            asyncio.create_task(self._monitor_nats_topics())
            
        except Exception as e:
            self.logger.error(f"Failed to connect to NATS: {e}")
            self.nats_connected = False
    
    async def _nats_error_cb(self, e):
        """NATS error callback"""
        self.logger.error(f"NATS error: {e}")
    
    async def _nats_disconnected_cb(self):
        """NATS disconnection callback"""
        self.logger.warning("NATS disconnected")
        self.nats_connected = False
    
    async def _nats_reconnected_cb(self):
        """NATS reconnection callback"""
        self.logger.info("NATS reconnected")
        self.nats_connected = True
    
    async def _monitor_nats_topics(self):
        """Monitor NATS topics for activity"""
        if not self.js:
            return
            
        topics_to_monitor = [
            'chat.questions',
            'documents.download', 
            'documents.chunks',
            'documents.embeddings',
            'system.metrics'
        ]
        
        while self.nats_connected:
            try:
                topic_stats = {}
                
                # Get stream info for each topic
                for topic in topics_to_monitor:
                    try:
                        # Try to get stream info (topics are usually stream subjects)
                        streams = await self.js.streams_info()
                        
                        for stream_info in streams:
                            stream = stream_info.config.name
                            subjects = stream_info.config.subjects or []
                            
                            # Check if our topic matches any subject in this stream
                            if topic in subjects or any(topic in subject for subject in subjects):
                                topic_stats[topic] = {
                                    'messages': stream_info.state.messages,
                                    'bytes': stream_info.state.bytes,
                                    'consumers': stream_info.state.consumer_count,
                                    'last_sequence': stream_info.state.last_seq,
                                    'first_sequence': stream_info.state.first_seq,
                                    'last_time': stream_info.state.last_ts,
                                    'status': 'active' if stream_info.state.messages > 0 else 'idle'
                                }
                                break
                        else:
                            # Topic not found in any stream
                            topic_stats[topic] = {
                                'messages': 0,
                                'bytes': 0,
                                'consumers': 0,
                                'status': 'idle'
                            }
                            
                    except Exception as e:
                        self.logger.error(f"Failed to get stats for topic {topic}: {e}")
                        topic_stats[topic] = {
                            'messages': 0,
                            'bytes': 0, 
                            'consumers': 0,
                            'status': 'error'
                        }
                
                # Update session state with topic stats
                st.session_state.nats_metrics['topics'] = topic_stats
                st.session_state.nats_metrics['last_updated'] = datetime.now()
                
                # Wait before next check
                await asyncio.sleep(5)
                
            except Exception as e:
                self.logger.error(f"NATS monitoring error: {e}")
                await asyncio.sleep(10)
    
    def _render_nats_topics_section(self):
        """Render NATS topics monitoring section"""
        st.subheader("📡 NATS Topic Monitoring")
        
        if not self.nats_connected:
            st.warning("🟡 NATS connection not established. Attempting to connect...")
            return
        
        # Connection status
        col1, col2 = st.columns([3, 1])
        with col1:
            st.success(f"🟢 Connected to NATS at {self.nats_url}")
        with col2:
            if st.button("🔄 Refresh Topics", type="secondary"):
                st.rerun()
        
        # Topics status
        topics_data = st.session_state.nats_metrics.get('topics', {})
        last_updated = st.session_state.nats_metrics.get('last_updated')
        
        if not topics_data:
            st.info("📊 Collecting topic statistics...")
            return
        
        # Display topic status cards
        cols = st.columns(len(topics_data))
        
        for i, (topic, stats) in enumerate(topics_data.items()):
            with cols[i]:
                status = stats.get('status', 'unknown')
                messages = stats.get('messages', 0)
                consumers = stats.get('consumers', 0)
                
                # Status indicator
                if status == 'active':
                    status_color = "🟢"
                    status_text = "Active"
                elif status == 'idle':
                    status_color = "⚪"
                    status_text = "Idle"
                else:
                    status_color = "🔴"
                    status_text = "Error"
                
                st.markdown(f"""
                <div style="
                    padding: 1rem;
                    border-radius: 8px;
                    border-left: 4px solid {'#28a745' if status == 'active' else '#ffc107' if status == 'idle' else '#dc3545'};
                    background: {'#e8f5e9' if status == 'active' else '#fff3cd' if status == 'idle' else '#f8d7da'};
                    margin-bottom: 1rem;
                ">
                    <div style="font-weight: bold; margin-bottom: 0.5rem;">
                        {status_color} {topic.replace('.', ' ').title()}
                    </div>
                    <div style="font-size: 0.9em; color: #666;">
                        Status: {status_text}<br>
                        Messages: {messages}<br>
                        Consumers: {consumers}
                    </div>
                </div>
                """, unsafe_allow_html=True)
        
        if last_updated:
            st.caption(f"Last updated: {last_updated.strftime('%H:%M:%S')}")
    
    def _initialize_websocket_integration(self):
        """Initialize WebSocket integration for live dashboard updates"""
        try:
            from .websocket_client import get_websocket_client, initialize_websocket_integration, ensure_websocket_connection
            
            # Initialize WebSocket if not already done
            if not st.session_state.get('websocket_dashboard_initialized', False):
                initialize_websocket_integration()
                st.session_state.websocket_dashboard_initialized = True
            
            # Check for live metric updates
            if ensure_websocket_connection():
                self._process_websocket_metrics()
                
        except ImportError:
            # WebSocket client not available, dashboard will use polling only
            self.logger.debug("WebSocket client not available for dashboard")
    
    def _process_websocket_metrics(self):
        """Process WebSocket messages for live metric updates"""
        try:
            from .websocket_client import get_websocket_client
            
            ws_client = get_websocket_client()
            if not ws_client:
                return
            
            # Get queued messages
            messages = ws_client.get_queued_messages()
            
            for message in messages:
                if message.get('type') == 'metrics_update':
                    # Update dashboard metrics from WebSocket
                    metrics_data = message.get('data', {})
                    
                    # Update NATS metrics if available
                    if 'nats_topics' in metrics_data:
                        st.session_state.nats_metrics['topics'] = metrics_data['nats_topics']
                        st.session_state.nats_metrics['last_updated'] = datetime.now()
                    
                    # Update system metrics if available
                    if 'system_metrics' in metrics_data:
                        system_metrics = metrics_data['system_metrics']
                        current_time = datetime.now()
                        
                        # Add to dashboard metrics history
                        self._add_metric_point(current_time, system_metrics)
                
                elif message.get('type') == 'system_alert':
                    # Handle system alerts
                    alert_data = message.get('data', {})
                    self._display_system_alert(alert_data)
                    
        except Exception as e:
            self.logger.error(f"Failed to process WebSocket metrics: {e}")
    
    def _add_metric_point(self, timestamp: datetime, metrics: Dict[str, Any]):
        """Add a metric data point to the dashboard history"""
        max_history = 50
        
        # Ensure all metric lists exist
        for key in ['timestamps', 'active_sessions', 'questions_asked', 'documents_processed', 'response_times']:
            if key not in st.session_state.dashboard_metrics:
                st.session_state.dashboard_metrics[key] = []
        
        # Add new data point
        st.session_state.dashboard_metrics['timestamps'].append(timestamp)
        st.session_state.dashboard_metrics['active_sessions'].append(metrics.get('active_sessions', 0))
        st.session_state.dashboard_metrics['questions_asked'].append(metrics.get('questions_asked', 0))
        st.session_state.dashboard_metrics['documents_processed'].append(metrics.get('documents_processed', 0))
        st.session_state.dashboard_metrics['response_times'].append(metrics.get('avg_response_time', 0.0))
        
        # Trim history to max length
        for key, values in st.session_state.dashboard_metrics.items():
            if len(values) > max_history:
                st.session_state.dashboard_metrics[key] = values[-max_history:]
    
    def _display_system_alert(self, alert_data: Dict[str, Any]):
        """Display system alerts on dashboard"""
        alert_type = alert_data.get('level', 'info')
        message = alert_data.get('message', 'System notification')
        
        if alert_type == 'error':
            st.error(f"🚨 System Alert: {message}")
        elif alert_type == 'warning':
            st.warning(f"⚠️ System Warning: {message}")
        elif alert_type == 'success':
            st.success(f"✅ System Update: {message}")
        else:
            st.info(f"ℹ️ System Info: {message}")
    
    def get_websocket_status(self) -> Dict[str, Any]:
        """Get WebSocket connection status for dashboard display"""
        try:
            from .websocket_client import get_websocket_client
            
            ws_client = get_websocket_client()
            if ws_client:
                return {
                    'connected': ws_client.connected,
                    'last_message': ws_client.last_message_time,
                    'message_count': len(ws_client.get_queued_messages())
                }
        except ImportError:
            pass
        
        return {
            'connected': False,
            'last_message': None,
            'message_count': 0
        }


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