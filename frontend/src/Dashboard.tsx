import { useEffect, useState } from 'react'
import { Bar, Line } from 'react-chartjs-2'
import {
    Chart as ChartJS,
    CategoryScale,
    LinearScale,
    BarElement,
    LineElement,
    PointElement,
    Title,
    Tooltip,
    Legend,
} from 'chart.js'

ChartJS.register(
    CategoryScale,
    LinearScale,
    BarElement,
    LineElement,
    PointElement,
    Title,
    Tooltip,
    Legend
)

interface ScoreBucket {
    bucket: string
    count: number
}

interface TimelinePoint {
    date: string
    submissions: number
}

export default function Dashboard() {
    const [labId, setLabId] = useState('lab-04')
    const [scores, setScores] = useState<ScoreBucket[]>([])
    const [timeline, setTimeline] = useState<TimelinePoint[]>([])
    const [loading, setLoading] = useState(false)
    const [error, setError] = useState<string | null>(null)

    useEffect(() => {
        const token = localStorage.getItem('api_key')

        async function loadData() {
            if (!token) {
                setError('API key not found in localStorage')
                return
            }

            setLoading(true)
            setError(null)

            try {
                const headers = {
                    Authorization: `Bearer ${token}`,
                }

                const [scoresRes, timelineRes] = await Promise.all([
                    fetch(`/analytics/scores?lab=${labId}`, { headers }),
                    fetch(`/analytics/timeline?lab=${labId}`, { headers }),
                ])

                if (!scoresRes.ok) {
                    throw new Error(`Scores request failed: HTTP ${scoresRes.status}`)
                }

                if (!timelineRes.ok) {
                    throw new Error(`Timeline request failed: HTTP ${timelineRes.status}`)
                }

                const scoresData: ScoreBucket[] = await scoresRes.json()
                const timelineData: TimelinePoint[] = await timelineRes.json()

                setScores(scoresData)
                setTimeline(timelineData)
            } catch (e) {
                setError(e instanceof Error ? e.message : 'Unknown error')
            } finally {
                setLoading(false)
            }
        }

        void loadData()
    }, [labId])

    if (loading) {
        return <div>Loading dashboard...</div>
    }

    if (error) {
        return <div>Error: {error}</div>
    }

    const scoreChartData = {
        labels: scores.map((item) => item.bucket),
        datasets: [
            {
                label: 'Score distribution',
                data: scores.map((item) => item.count),
            },
        ],
    }

    const timelineChartData = {
        labels: timeline.map((item) => item.date),
        datasets: [
            {
                label: 'Submissions over time',
                data: timeline.map((item) => item.submissions),
            },
        ],
    }

    return (
        <div style={{ padding: '20px' }}>
            <h2>Dashboard</h2>

            <div style={{ marginBottom: '20px' }}>
                <label htmlFor="lab-select">Select lab: </label>
                <select
                    id="lab-select"
                    value={labId}
                    onChange={(e) => setLabId(e.target.value)}
                >
                    <option value="lab-04">lab-04</option>
                    <option value="lab-05">lab-05</option>
                </select>
            </div>

            <div style={{ maxWidth: '800px', marginBottom: '40px' }}>
                <h3>Score Distribution</h3>
                <Bar data={scoreChartData} />
            </div>

            <div style={{ maxWidth: '800px', marginBottom: '40px' }}>
                <h3>Timeline</h3>
                <Line data={timelineChartData} />
            </div>
        </div>
    )
}