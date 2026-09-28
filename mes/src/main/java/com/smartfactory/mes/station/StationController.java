package com.smartfactory.mes.station;

import java.time.Instant;
import java.util.List;

import com.fasterxml.jackson.annotation.JsonProperty;

import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/api/stations")
public class StationController {

    private final StationService stations;

    public StationController(StationService stations) {
        this.stations = stations;
    }

    @GetMapping
    public List<StationView> list() {
        return stations.all().stream()
                .map(s -> new StationView(s.getStationId(), s.getState(), s.getUpdatedAt()))
                .toList();
    }

    public record StationView(
            @JsonProperty("station_id") String stationId,
            @JsonProperty("state") String state,
            @JsonProperty("updated_at") Instant updatedAt) {
    }
}
