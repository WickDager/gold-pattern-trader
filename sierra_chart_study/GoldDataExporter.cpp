#include "sierrachart.h"
#include <fstream>
#include <deque>
#include <iomanip>

SCDLLName("GoldDataExporter_1Min")

    /* ---------------------------------------------------------------------------
     * RollingBarData
     *
     * Stores a single 1-minute bar together with computed pattern markers, the
     * cumulative delta value and the ADR (Average Daily Range) from companion
     * studies on the chart.
     * -------------------------------------------------------------------------*/
    struct RollingBarData
{
    SCDateTime datetime;
    float open;
    float high;
    float low;
    float close;
    float volume;

    float pattern_high;
    float pattern_low;
    float pattern_type; // 1 = swing-high, -1 = swing-low, 0 = none
    float cumulative_delta;
    float adr_value;
};

static std::deque<RollingBarData> rollingWindow;
static const int ROLLING_WINDOW_SIZE = 60; // keep 60 one-minute bars
static const int INITIALIZATION_BARS = 15; // warm-up bars on first load
static bool isInitialized = false;
static int lastProcessedIndex = -1;

/* ---------------------------------------------------------------------------
 * Expiration helper
 *
 * Once the current trading-day date passes the hard-coded expiration the
 * study silently stops producing output.
 * -------------------------------------------------------------------------*/
static bool IsExpired(SCStudyInterfaceRef sc)
{
    SCDateTime currentDateTime = sc.GetTradingDayDate(sc.ChartNumber);

    SCDateTime expirationDate;
    expirationDate.SetDate(20280114);

    return currentDateTime >= expirationDate;
}

/* forward declaration */
static void WriteCSVFile(SCStudyInterfaceRef sc, const char *filePath);

/* ---------------------------------------------------------------------------
 * Main ACSIL export function
 * -------------------------------------------------------------------------*/
SCSFExport scsf_GoldDataExporter(SCStudyInterfaceRef sc)
{
    /* ---- expiration gate ------------------------------------------------*/
    if (IsExpired(sc))
        return;

    /* ---- sub-graphs (visual output on the chart) ------------------------*/
    SCSubgraphRef s_PatternHigh = sc.Subgraph[0];
    SCSubgraphRef s_PatternLow = sc.Subgraph[1];
    SCSubgraphRef s_CumulativeDelta = sc.Subgraph[2];
    SCSubgraphRef s_ADR = sc.Subgraph[3];
    SCSubgraphRef s_PatternType = sc.Subgraph[4];

    /* ---- inputs (configured by the user) --------------------------------*/
    SCInputRef i_ADRStudySubgraph = sc.Input[0];
    SCInputRef i_CumulativeDeltaStudySubgraph = sc.Input[1];
    SCInputRef i_OutputPath = sc.Input[2];

    /* ---- defaults (called once when the study is first created) ---------*/
    if (sc.SetDefaults)
    {
        sc.GraphName = "GoldDataExporter_1Min";
        sc.StudyDescription = "Exports live 1-minute gold data with pattern markers";
        sc.AutoLoop = 1;
        sc.GraphRegion = 0;
        sc.FreeDLL = 1;
        sc.UpdateAlways = 0;

        s_PatternHigh.Name = "Pattern High";
        s_PatternHigh.DrawStyle = DRAWSTYLE_POINT;
        s_PatternHigh.PrimaryColor = RGB(255, 0, 0);
        s_PatternHigh.LineWidth = 5;

        s_PatternLow.Name = "Pattern Low";
        s_PatternLow.DrawStyle = DRAWSTYLE_POINT;
        s_PatternLow.PrimaryColor = RGB(0, 255, 0);
        s_PatternLow.LineWidth = 5;

        s_CumulativeDelta.Name = "Cumulative Delta";
        s_CumulativeDelta.DrawStyle = DRAWSTYLE_IGNORE;

        s_ADR.Name = "ADR Value";
        s_ADR.DrawStyle = DRAWSTYLE_IGNORE;

        s_PatternType.Name = "Pattern Type";
        s_PatternType.DrawStyle = DRAWSTYLE_IGNORE;

        i_ADRStudySubgraph.Name = "ADR Study Subgraph";
        i_ADRStudySubgraph.SetStudySubgraphValues(0, 0);

        i_CumulativeDeltaStudySubgraph.Name = "Cumulative Delta Subgraph";
        i_CumulativeDeltaStudySubgraph.SetStudySubgraphValues(0, 3);

        i_OutputPath.Name = "Output File Path";
        i_OutputPath.SetString("C:\\trading_bot\\Live_Gold_Data.csv");

        return;
    }

    /* ====================================================================
     * ONE-TIME INITIALIZATION  (process last INITIALIZATION_BARS bars)
     * ====================================================================*/
    if (!isInitialized)
    {
        rollingWindow.clear();
        lastProcessedIndex = -1;

        int startIndex = sc.ArraySize - INITIALIZATION_BARS;
        if (startIndex < 0)
            startIndex = 0;

        sc.AddMessageToLog("Initializing with limited historical data...", 0);

        SCFloatArray adrArray, cumDeltaArray;
        sc.GetStudyArrayFromChartUsingID(
            sc.ChartNumber,
            i_ADRStudySubgraph.GetStudyID(),
            i_ADRStudySubgraph.GetSubgraphIndex(),
            adrArray);

        sc.GetStudyArrayFromChartUsingID(
            sc.ChartNumber,
            i_CumulativeDeltaStudySubgraph.GetStudyID(),
            i_CumulativeDeltaStudySubgraph.GetSubgraphIndex(),
            cumDeltaArray);

        for (int i = startIndex; i < sc.ArraySize - 1; ++i)
        {
            RollingBarData bar{};
            bar.datetime = sc.BaseDateTimeIn[i];
            bar.open = sc.Open[i];
            bar.high = sc.High[i];
            bar.low = sc.Low[i];
            bar.close = sc.Close[i];
            bar.volume = sc.Volume[i];

            if (i >= 2)
            {
                const float H0 = sc.High[i];
                const float L0 = sc.Low[i];
                const float H1 = sc.High[i - 1];
                const float L1 = sc.Low[i - 1];
                const float H2 = sc.High[i - 2];
                const float L2 = sc.Low[i - 2];

                if (H1 > H0 && H1 > H2)
                {
                    bar.pattern_high = H1;
                    bar.pattern_type = 1;
                    s_PatternHigh[i - 1] = H1;
                    s_PatternType[i - 1] = 1;
                }
                else if (L1 < L0 && L1 < L2)
                {
                    bar.pattern_low = L1;
                    bar.pattern_type = -1;
                    s_PatternLow[i - 1] = L1;
                    s_PatternType[i - 1] = -1;
                }
            }

            bar.adr_value = (i < adrArray.GetArraySize()) ? adrArray[i] : 0.0f;
            bar.cumulative_delta = (i < cumDeltaArray.GetArraySize()) ? cumDeltaArray[i] : 0.0f;

            s_CumulativeDelta[i] = bar.cumulative_delta;
            s_ADR[i] = bar.adr_value;

            rollingWindow.push_back(bar);
            while (rollingWindow.size() > ROLLING_WINDOW_SIZE)
                rollingWindow.pop_front();

            lastProcessedIndex = i;
        }

        isInitialized = true;
        WriteCSVFile(sc, i_OutputPath.GetString());

        SCString msg;
        msg.Format("Initialization complete. %d bars loaded. Last index: %d",
                   (int)rollingWindow.size(), lastProcessedIndex);
        sc.AddMessageToLog(msg, 0);

        /* fall through to process any new bar that arrived during init */
    }

    /* ====================================================================
     * LIVE PROCESSING  — process every new completed bar
     * ====================================================================*/
    int currentIndex = sc.Index;
    if (currentIndex < 2)
        return;

    int startProcessing = lastProcessedIndex + 1;
    int endProcessing = currentIndex - 1; // skip the still-forming bar

    if (startProcessing > endProcessing)
        return;

    /* Grab study arrays once for the batch */
    SCFloatArray adrArray, cumDeltaArray;
    sc.GetStudyArrayFromChartUsingID(
        sc.ChartNumber,
        i_ADRStudySubgraph.GetStudyID(),
        i_ADRStudySubgraph.GetSubgraphIndex(),
        adrArray);

    sc.GetStudyArrayFromChartUsingID(
        sc.ChartNumber,
        i_CumulativeDeltaStudySubgraph.GetStudyID(),
        i_CumulativeDeltaStudySubgraph.GetSubgraphIndex(),
        cumDeltaArray);

    bool wroteFile = false;

    for (int bi = startProcessing; bi <= endProcessing; ++bi)
    {
        /* reset pattern markers for this bar index */
        s_PatternHigh[bi] = 0.0f;
        s_PatternLow[bi] = 0.0f;
        s_PatternType[bi] = 0.0f;

        RollingBarData bar{};
        bar.datetime = sc.BaseDateTimeIn[bi];
        bar.open = sc.Open[bi];
        bar.high = sc.High[bi];
        bar.low = sc.Low[bi];
        bar.close = sc.Close[bi];
        bar.volume = sc.Volume[bi];

        if (bi >= 2)
        {
            const float H_curr = sc.High[bi];
            const float L_curr = sc.Low[bi];
            const float H_prev = sc.High[bi - 1];
            const float L_prev = sc.Low[bi - 1];
            const float H_prev2 = sc.High[bi - 2];
            const float L_prev2 = sc.Low[bi - 2];

            if (H_prev > H_curr && H_prev > H_prev2)
            {
                bar.pattern_high = H_prev;
                bar.pattern_type = 1;
                s_PatternHigh[bi - 1] = H_prev;
                s_PatternType[bi - 1] = 1;
            }
            else if (L_prev < L_curr && L_prev < L_prev2)
            {
                bar.pattern_low = L_prev;
                bar.pattern_type = -1;
                s_PatternLow[bi - 1] = L_prev;
                s_PatternType[bi - 1] = -1;
            }
        }

        bar.adr_value = (bi < adrArray.GetArraySize()) ? adrArray[bi] : 0.0f;
        bar.cumulative_delta = (bi < cumDeltaArray.GetArraySize()) ? cumDeltaArray[bi] : 0.0f;

        s_CumulativeDelta[bi] = bar.cumulative_delta;
        s_ADR[bi] = bar.adr_value;

        rollingWindow.push_back(bar);
        while (rollingWindow.size() > ROLLING_WINDOW_SIZE)
            rollingWindow.pop_front();

        lastProcessedIndex = bi;
        wroteFile = true;

        SCString msg;
        msg.Format("Processed bar index %d", bi);
        sc.AddMessageToLog(msg, 0);
    }

    if (wroteFile)
        WriteCSVFile(sc, i_OutputPath.GetString());
}

/* ---------------------------------------------------------------------------
 * WriteCSVFile  — dump the rolling window to disk as CSV
 * -------------------------------------------------------------------------*/
static void WriteCSVFile(SCStudyInterfaceRef sc, const char *filePath)
{
    if (IsExpired(sc))
        return;

    if (rollingWindow.empty())
    {
        sc.AddMessageToLog("Rolling window empty — skipping CSV write", 0);
        return;
    }

    std::ofstream out(filePath);
    if (!out.is_open())
    {
        SCString msg;
        msg.Format("Failed to open output file: %s", filePath);
        sc.AddMessageToLog(msg, 1);
        return;
    }

    out << "datetime,open,high,low,close,volume,"
           "pattern_high,pattern_low,pattern_type,"
           "cumulative_delta,adr_value\n";

    for (const auto &bar : rollingWindow)
    {
        SCString dt = sc.FormatDateTime(bar.datetime);
        out << dt.GetChars() << ","
            << std::fixed << std::setprecision(5) << bar.open << ","
            << std::fixed << std::setprecision(5) << bar.high << ","
            << std::fixed << std::setprecision(5) << bar.low << ","
            << std::fixed << std::setprecision(5) << bar.close << ","
            << std::fixed << std::setprecision(0) << bar.volume << ","
            << std::fixed << std::setprecision(5) << bar.pattern_high << ","
            << std::fixed << std::setprecision(5) << bar.pattern_low << ","
            << std::fixed << std::setprecision(0) << bar.pattern_type << ","
            << std::fixed << std::setprecision(2) << bar.cumulative_delta << ","
            << std::fixed << std::setprecision(5) << bar.adr_value << "\n";
    }

    SCString msg;
    msg.Format("CSV written: %d bars", (int)rollingWindow.size());
    sc.AddMessageToLog(msg, 0);
}
