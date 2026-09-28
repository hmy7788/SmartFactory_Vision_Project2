package com.smartfactory.mes.station;

import java.util.List;

import com.smartfactory.mes.message.StatusMessage;

import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

@Service
public class StationService {

    private final StationRepository stations;

    public StationService(StationRepository stations) {
        this.stations = stations;
    }

    @Transactional
    public void onStatus(String stationId, StatusMessage status) {
        Station s = stations.findById(stationId).orElseGet(() -> new Station(stationId));
        s.update(status.state() == null ? "unknown" : status.state());
        stations.save(s);
    }

    @Transactional(readOnly = true)
    public List<Station> all() {
        return stations.findAll();
    }
}
