#include "rclcpp/rclcpp.hpp"
#include <algorithm>
#include <chrono>
#include <fstream>
#include <memory>
#include <regex>
#include <sstream>
#include <string>
#include <vector>

std::shared_ptr<rclcpp::Node> nodeptr3 = nullptr;

class ParameterParser : public rclcpp::Node
{
public:
    ParameterParser() : Node("ParameterParser")
    {
        this->declare_parameter("device_name", rclcpp::PARAMETER_STRING);
        this->declare_parameter("mmwavecli_cfg", rclcpp::PARAMETER_STRING);
    }
};

int main(int argc, char **argv) {

    float c0 = 299792458;
    int chirpStartIdx;
    int chirpEndIdx;
    int numLoops;
    int numFrames;
    float framePeriodicity;
    float startFreq;
    float idleTime;
    float adcStartTime;
    float rampEndTime;
    float digOutSampleRate;
    float freqSlopeConst;
    float numAdcSamples;
    float zoneMinX;
    float zoneMaxX;
    float zoneMinY;
    float zoneMaxY;
    float zoneMinZ;
    float zoneMaxZ;

    rclcpp::init(argc, argv);
    nodeptr3 = std::make_shared<ParameterParser>();
    std::string token;
    std::ifstream myCfgParam;
    std::string str_param;
    std::string deviceName = nodeptr3->get_parameter("device_name").as_string();
    std::string mmWaveCLIcfg = nodeptr3->get_parameter("mmwavecli_cfg").as_string();
    myCfgParam.open(mmWaveCLIcfg);

    if (deviceName.compare("6432") != 0)
    {
        if (myCfgParam.is_open())
        {
            while( std::getline(myCfgParam, str_param))
            {
                str_param.erase(std::remove(str_param.begin(), str_param.end(), '\r'), str_param.end());
                if (!(std::regex_match(str_param, std::regex("^\\s*%.*")) || std::regex_match(str_param, std::regex("^\\s*$"))))
                {
                    std::istringstream ss(str_param);
                    std::vector <std::string> v;
                    while(ss >> token)
                    {
                        v.push_back(token);
                    }

                    if (v.empty())
                    {
                        continue;
                    }

                    if (!v[0].compare("profileCfg"))
                    {
                        startFreq = std::stof(v[2]);
                        idleTime = std::stof(v[3]);
                        adcStartTime = std::stof(v[4]);
                        rampEndTime = std::stof(v[5]);
                        freqSlopeConst = std::stof(v[8]);
                        numAdcSamples = std::stof(v[10]);
                        digOutSampleRate = std::stof(v[11]);
                    }
                    else if (!v[0].compare("frameCfg"))
                    {
                        chirpStartIdx = std::stoi(v[1]);
                        chirpEndIdx = std::stoi(v[2]);
                        numLoops = std::stoi(v[3]);
                        numFrames = std::stoi(v[4]);
                        framePeriodicity = std::stof(v[5]);
                    }
                    else if (!v[0].compare("zoneDef"))
                    {
                        zoneMinX = std::stof(v[2]);
                        zoneMaxX = std::stof(v[3]);
                        zoneMinY = std::stof(v[4]);
                        zoneMaxY = std::stof(v[5]);
                        zoneMinZ = std::stof(v[6]);
                        zoneMaxZ = std::stof(v[7]);
                    }
                }
            }
        }

        int ntx = chirpEndIdx - chirpStartIdx + 1;
        int nd = numLoops;
        int nr = numAdcSamples;
        float tfr = framePeriodicity * 1e-3;
        float fs = digOutSampleRate * 1e3;
        float kf = freqSlopeConst * 1e12;
        float adc_duration = nr / fs;
        float BW = adc_duration * kf;
        float PRI = (idleTime + rampEndTime) * 1e-6;
        float fc = startFreq * 1e9 + kf * (adcStartTime * 1e-6 + adc_duration / 2);
        float vrange = c0 / (2 * BW);
        float max_range = nr * vrange;
        float max_vel = c0 / (2 * fc * PRI) / ntx;
        float vvel = max_vel / nd;
        std::this_thread::sleep_for(std::chrono::milliseconds(2000));
        RCLCPP_INFO(rclcpp::get_logger("rclcpp"),"\n\n==============================\nList of parameters\n==============================\nNumber of range samples: %d\nNumber of chirps: %d\nf_s: %.3f MHz\nf_c: %.3f GHz\nBandwidth: %.3f MHz\nPRI: %.3f us\nFrame time: %.3f ms\nMax range: %.3f m\nRange resolution: %.3f m\nMax Doppler: +-%.3f m/s\nDoppler resolution: %.3f m/s\n==============================\n",
            nr, nd, fs/1e6, fc/1e9, BW/1e6, PRI*1e6, tfr*1e3, max_range, vrange, max_vel/2, vvel);
    }
    nodeptr3.reset();
    rclcpp::shutdown();
    return 0;
}
