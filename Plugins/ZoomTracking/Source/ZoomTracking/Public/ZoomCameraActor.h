#pragma once

#include "CoreMinimal.h"
#include "CineCameraActor.h"
#include "InputCoreTypes.h"
#include "ZoomCameraActor.generated.h"

class UTextureRenderTarget2D;
class UMaterialParameterCollection;

/** Who decides the person plate depth. */
UENUM(BlueprintType)
enum class EPersonDepthCue : uint8
{
	Auto  UMETA(DisplayName = "Auto (distance estimate)"),
	Front UMETA(DisplayName = "Front (operator)"),
	Back  UMETA(DisplayName = "Back (operator)"),
};

/** One frame of the matte code row. */
struct FZoomCodeFrame
{
	bool bZoomValid = false;
	float Scale = 1.0f;
	bool bDistanceValid = false;
	float DistanceM = 0.0f;
};

/**
 * Cine camera driven by the lens zoom that Python (rvm_main --zoom-source ...) writes into the
 * RVM matte, top-left code row (alpha 0, invisible):
 *   block 0 (x 0..3)   person distance in mm (R,G), B=255 when valid
 *   block 1 (x 4..7)   signature: R=0 G=255 B=0
 *   block 5 (x 20..23) zoom: R,G = ln(scale)/ln(256) in 16 bit, B=255 when valid
 * scale = focal / wide focal. The code is read from the same Spout frame the plates show,
 * so CG and video change zoom on the same frame.
 *
 * Attached actors tagged PlateTag are video plates (engine 100x100 plane, facing the camera);
 * they are re-sized every tick to exactly fill the frame at their distance.
 * The plate tagged PersonPlateTag is also moved to the person's distance, so CG between the
 * camera and the person covers them and CG behind them is covered (walk-through effect).
 *
 * Operator cue (keys while playing, default F / G / A): Front / Back put the person plate at a
 * fixed depth, Auto follows the distance estimate again. Every change eases over CueMoveTime.
 */
UCLASS(Blueprintable, ClassGroup = (Zoom), meta = (DisplayName = "Zoom Camera"))
class ZOOMTRACKING_API AZoomCameraActor : public ACineCameraActor
{
	GENERATED_BODY()

public:
	AZoomCameraActor(const FObjectInitializer& ObjectInitializer);

	virtual void Tick(float DeltaSeconds) override;
	virtual bool ShouldTickIfViewportsOnly() const override { return bPreviewInEditor; }

	/** Spout render target carrying the matte code (RT_RVM_OUTPUT). */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Zoom")
	TObjectPtr<UTextureRenderTarget2D> CodeTexture;

	/** Follow the code. Off: ManualScale is used. */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Zoom")
	bool bUseCode = true;

	/** Focal length (mm) at scale 1 = lens full wide. UA107x8.4: 8.4. */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Zoom", meta = (ClampMin = "1.0"))
	float WideFocalLength = 8.4f;

	/** Scale used when bUseCode is off (testing). */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Zoom", meta = (ClampMin = "1.0", ClampMax = "256.0"))
	float ManualScale = 1.0f;

	/** Also run in the editor viewport (live Spout preview). The camera is changed in the level, so reset before saving. */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Zoom")
	bool bPreviewInEditor = false;

	/** Re-size attached plates to fill the frame. */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Zoom|Plates")
	bool bFitPlates = true;

	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Zoom|Plates")
	FName PlateTag = TEXT("ZoomPlate");

	/** Plate mesh edge length in cm (engine Plane = 100). */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Zoom|Plates")
	float PlateMeshSize = 100.0f;

	/** Move the person plate to the estimated person distance. */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Zoom|Person Depth")
	bool bUsePersonDepth = true;

	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Zoom|Person Depth")
	FName PersonPlateTag = TEXT("PersonPlate");

	/** Plate depth (cm) = DepthOffset + distance (m) x DepthPerMeter. 100 = real scale. */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Zoom|Person Depth")
	float DepthPerMeter = 100.0f;

	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Zoom|Person Depth")
	float DepthOffset = 0.0f;

	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Zoom|Person Depth", meta = (ClampMin = "10.0"))
	float MinPersonDepth = 100.0f;

	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Zoom|Person Depth")
	float MaxPersonDepth = 5000.0f;

	/**
	 * Optional MPC that receives PersonDepth (cm, current person plate depth) and PassBand every
	 * tick, so object materials can dissolve where the person passes through them.
	 */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Zoom|Person Depth")
	TObjectPtr<UMaterialParameterCollection> DepthParameters;

	/** Depth range (cm) behind an object over which it fades out in front of the person. */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Zoom|Person Depth", meta = (ClampMin = "1.0"))
	float PassBand = 150.0f;

	/** Operator cue keys while playing (look at the Unreal view and press). */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Zoom|Person Cue")
	bool bEnableCueKeys = true;

	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Zoom|Person Cue")
	FKey FrontKey = EKeys::F;

	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Zoom|Person Cue")
	FKey BackKey = EKeys::G;

	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Zoom|Person Cue")
	FKey AutoKey = EKeys::A;

	/** Person plate depth (cm) for the Front cue: in front of the objects. */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Zoom|Person Cue")
	float CueFrontDepth = 400.0f;

	/** Person plate depth (cm) for the Back cue: behind the objects. */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Zoom|Person Cue")
	float CueBackDepth = 700.0f;

	/** Seconds for every cue change (eased, never jumps). */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Zoom|Person Cue", meta = (ClampMin = "0.05"))
	float CueMoveTime = 1.5f;

	/** Cue when Play starts. */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Zoom|Person Cue")
	EPersonDepthCue StartCue = EPersonDepthCue::Auto;

	UPROPERTY(VisibleInstanceOnly, BlueprintReadOnly, Category = "Zoom|Status")
	EPersonDepthCue CurrentCue = EPersonDepthCue::Auto;

	/** Change the cue now (eases from the current depth). */
	UFUNCTION(BlueprintCallable, Category = "Zoom")
	void SetPersonCue(EPersonDepthCue NewCue);

	/** Depth used until the first valid distance arrives. */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Zoom|Person Depth")
	float DefaultPersonDepth = 1000.0f;

	/** Current zoom scale (held at the last valid value when the code is missing). */
	UPROPERTY(VisibleInstanceOnly, BlueprintReadOnly, Category = "Zoom|Status")
	float CurrentScale = 1.0f;

	/** Code signature found and the zoom block is flagged valid this frame. */
	UPROPERTY(VisibleInstanceOnly, BlueprintReadOnly, Category = "Zoom|Status")
	bool bCodeValid = false;

	/** Last valid person distance from the code, m. */
	UPROPERTY(VisibleInstanceOnly, BlueprintReadOnly, Category = "Zoom|Status")
	float PersonDistanceM = 0.0f;

	UPROPERTY(VisibleInstanceOnly, BlueprintReadOnly, Category = "Zoom|Status")
	bool bDistanceValid = false;

	/** Person plate distance from the camera, cm. */
	UPROPERTY(VisibleInstanceOnly, BlueprintReadOnly, Category = "Zoom|Status")
	float CurrentPersonDepth = 1000.0f;

	/** Time spent reading the code back from the GPU, ms. */
	UPROPERTY(VisibleInstanceOnly, BlueprintReadOnly, Category = "Zoom|Status")
	float ReadbackMs = 0.0f;

	/** Current horizontal field of view in degrees. */
	UFUNCTION(BlueprintPure, Category = "Zoom")
	float GetHorizontalFOV() const;

	/** Apply a scale now (also used internally). */
	UFUNCTION(BlueprintCallable, Category = "Zoom")
	void ApplyScale(float Scale);

	/** Move the person plate to a depth (cm) now. */
	UFUNCTION(BlueprintCallable, Category = "Zoom")
	void ApplyPersonDepth(float Depth);

	/** Re-size the tagged plates to the current field of view. */
	UFUNCTION(BlueprintCallable, Category = "Zoom")
	void FitPlates();

private:
	virtual void BeginPlay() override;
	bool ReadCode(FZoomCodeFrame& Out);
	void PollCueKeys();
	bool bCueBlending = false;
	float CueFromDepth = 0.0f;
	double CueStartTime = 0.0;
	bool bHasDistance = false;
	double LastLogTime = 0.0;
};
